"""
generator.py — Load Gautamo1/mistral-7b-rag-reader and run inference
Optimised for AMD MI300X / high-VRAM (192 GB) GPUs running ROCm.
"""
from __future__ import annotations

import os
from loguru import logger


PROMPT_TEMPLATE = """\
You are a helpful policy assistant. Use ONLY the provided context to answer the question.
If the answer is not in the context, say "I don't have enough information in the provided documents."

Context:
{context}

Question: {question}

Answer:"""


class Generator:
    """
    Wraps the fine-tuned Mistral-7B RAG reader.

    MI300X / 192 GB VRAM optimisations applied:
      - Full bfloat16, no quantisation needed
      - torch.compile() with reduce-overhead mode (ROCm-compatible)
      - Flash Attention 2 for faster prefill on long RAG contexts
      - Batched inference support for concurrent requests
      - flash_attn_2 available via transformers attn_implementation
    """

    def __init__(
        self,
        model_name: str = "Gautamo1/mistral-7b-rag-reader",
        torch_dtype: str = "bfloat16",
        device_map: str = "auto",
        max_new_tokens: int = 512,
        temperature: float = 0.1,
        do_sample: bool = False,
        compile_model: bool = True,
    ):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.do_sample = do_sample

        dtype = getattr(torch, torch_dtype) if isinstance(torch_dtype, str) else torch_dtype

        logger.info(f"Loading tokenizer: {model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.tokenizer.padding_side = "left"   # required for batched generation

        logger.info(f"Loading model: {model_name} (dtype={torch_dtype}, FlashAttn2, device={device_map})")
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=dtype,
            device_map=device_map,
            attn_implementation="flash_attention_2",  # faster prefill on long contexts
        )
        self.model.eval()

        # torch.compile — reduce-overhead is ROCm-compatible, gives ~20-30% throughput gain
        if compile_model:
            logger.info("Compiling model with torch.compile (mode=reduce-overhead)…")
            self.model = torch.compile(self.model, mode="reduce-overhead")
            logger.success("Model compiled")

        logger.success("Generator ready")

    # ── Prompt building ──────────────────────────────────────────

    @staticmethod
    def build_prompt(question: str, chunks: list[dict]) -> str:
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            context_parts.append(
                f"[{i}] (source: {chunk['source']})\n{chunk['text']}"
            )
        context = "\n\n".join(context_parts)
        return PROMPT_TEMPLATE.format(context=context, question=question)

    # ── Single generation ────────────────────────────────────────

    def generate(self, prompt: str) -> str:
        import torch

        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=4096,
        )
        device = next(self.model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        gen_kwargs = dict(
            **inputs,
            max_new_tokens=self.max_new_tokens,
            do_sample=self.do_sample,
            pad_token_id=self.tokenizer.eos_token_id,
            use_cache=True,
        )
        if self.do_sample:
            gen_kwargs["temperature"] = self.temperature

        with torch.no_grad():
            output_ids = self.model.generate(**gen_kwargs)

        new_ids = output_ids[0][inputs["input_ids"].shape[-1]:]
        return self.tokenizer.decode(new_ids, skip_special_tokens=True).strip()

    # ── Batched generation (use for concurrent API requests) ─────

    def generate_batch(self, prompts: list[str]) -> list[str]:
        """
        Generate answers for multiple prompts in a single forward pass.
        With 192 GB VRAM you can comfortably batch 32+ queries at once.
        """
        import torch

        inputs = self.tokenizer(
            prompts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=4096,
        )
        device = next(self.model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=self.do_sample,
                pad_token_id=self.tokenizer.eos_token_id,
                use_cache=True,
                **({"temperature": self.temperature} if self.do_sample else {}),
            )

        results = []
        input_len = inputs["input_ids"].shape[1]
        for ids in output_ids:
            new_ids = ids[input_len:]
            results.append(self.tokenizer.decode(new_ids, skip_special_tokens=True).strip())
        return results
