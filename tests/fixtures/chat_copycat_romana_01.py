import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
from peft import PeftModel

MODEL = "OpenLLM-Ro/RoMistral-7b-Instruct-2025-04-23"
ADAPTER = "copycat_romana_naturala_01_adapter"

print("Incarc Copycat...")

tokenizer = AutoTokenizer.from_pretrained(MODEL)

config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True,
)

base = AutoModelForCausalLM.from_pretrained(
    MODEL,
    device_map="auto",
    quantization_config=config,
)

model = PeftModel.from_pretrained(base, ADAPTER)
model.eval()

messages = []

print("\nCopycat este gata.")
print("Comenzi: /reset, exit")
print("Scrie fiecare prompt pe o singura linie.\n")

while True:
    user_text = input("TU > ").strip()

    if not user_text:
        continue

    if user_text.lower() in {"exit", "quit"}:
        break

    if user_text.lower() == "/reset":
        messages = []
        print("\nConversatie resetata.\n")
        continue

    messages.append({"role": "user", "content": user_text})

    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        system_message="Răspunde în română firească. Fii concis, păstrează sensul exact și respectă tonul cerut. Evită calcurile și nu inventa explicații."
    )

    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        add_special_tokens=False
    ).to(model.device)

    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=200,
            do_sample=False,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.pad_token_id,
        )

    generated = output[0][inputs["input_ids"].shape[1]:]
    answer = tokenizer.decode(generated, skip_special_tokens=True).strip()

    print("\nCOPYCAT >", answer, "\n")
    messages.append({"role": "assistant", "content": answer})
