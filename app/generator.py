"""
generator.py — Mistral-7B RAG reader, ROCm/MI300X optimised
"""
from __future__ import annotations
import os
from loguru import logger

# Mistral instruct format that matches how mistral-7b-rag-reader was fine-tuned
PROMPT_TEMPLATE = """<s>[INST] You are a document assistant. Answer the question using ONLY the context below.
Be direct and specific. If the answer is not in the context, say "Not found in document."

Context:
{context}

Question: {question} [/INST]"""


class Generator:
    def __init__(
        self,
        model_name: str = "Gautamo1/mistral-7b-rag-reader",
        torch_dtype: str = "bfloat16",
        device_map: str = "auto",
        max_new_tokens: int = 256,
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
        self.tokenizer.padding_side = "left"

        logger.info(f"Loading model: {model_name}")
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=dtype,
            device_map=device_map,
            attn_implementation="flash_attention_2",
        )
        self.model.eval()

        if compile_model:
            import torch
            logger.info("Compiling model...")
            self.model = torch.compile(self.model, mode="reduce-overhead")

        logger.success("Generator ready")

    @staticmethod
    def build_prompt(question: str, chunks: list[dict]) -> str:
        context = "\n\n".join(
            f"[{i+1}] {c['text']}" for i, c in enumerate(chunks)
        )
        return PROMPT_TEMPLATE.format(context=context, question=question)

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

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=self.do_sample,
                temperature=self.temperature if self.do_sample else None,
                pad_token_id=self.tokenizer.eos_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
                use_cache=True,
            )

        # Decode only newly generated tokens
        input_len = inputs["input_ids"].shape[-1]
        new_ids = output_ids[0][input_len:]
        answer = self.tokenizer.decode(new_ids, skip_special_tokens=True).strip()

        # Clean up any leaked prompt artifacts
        for stop in ["[INST]", "[/INST]", "</s>", "Question:", "Context:"]:
            if stop in answer:
                answer = answer.split(stop)[0].strip()

        return answer