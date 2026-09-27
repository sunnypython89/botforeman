"""Offline Copycat loader. No evaluator participates in model generation."""

import os
from pathlib import Path

MODEL = "OpenLLM-Ro/RoMistral-7b-Instruct-2025-04-23"


def load(adapter, trainable=False):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel, prepare_model_for_kbit_training

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; no remote or paid fallback")
    adapter = Path(adapter).resolve(strict=True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                              bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.float16)
    base = AutoModelForCausalLM.from_pretrained(
        MODEL, quantization_config=quant, device_map="auto", local_files_only=True)
    if trainable:
        base.config.use_cache = False
        base = prepare_model_for_kbit_training(base, use_gradient_checkpointing=True)
    model = PeftModel.from_pretrained(base, str(adapter), is_trainable=trainable,
                                     local_files_only=True)
    model.train() if trainable else model.eval()
    return model, tokenizer


def generate(model, tokenizer, prompt, max_new_tokens=384):
    import torch
    text = tokenizer.apply_chat_template([{"role": "user", "content": prompt}],
                                         tokenize=False, system_message="")
    inputs = tokenizer(text, return_tensors="pt", add_special_tokens=False).to(model.device)
    with torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                                eos_token_id=tokenizer.eos_token_id,
                                pad_token_id=tokenizer.pad_token_id)
    generated = output[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(generated, skip_special_tokens=True).strip(), len(generated)
