"""Tokenizer-only budget check. Runs with -I in the isolated venv; must stay free of MLX and of backend imports."""
import json
import sys


def count_tokens(tokenizer, text):
    """Same template as the upstream encoder, but never truncated: upstream truncates long prompts silently."""
    templated = tokenizer.apply_chat_template([{"role": "user", "content": text}], tokenize=False,
                                              add_generation_prompt=True, enable_thinking=True)
    return len(tokenizer(templated, truncation=False)["input_ids"])


def main():
    from transformers import AutoTokenizer

    request = json.load(sys.stdin)
    tokenizer = AutoTokenizer.from_pretrained(request["tokenizer"], local_files_only=True)
    print(json.dumps({"counts": [count_tokens(tokenizer, text) for text in request["texts"]]}))


if __name__ == "__main__":
    main()
