"""Run with python -m botforeman.demo. No model, files, or network required."""

from . import BotForeman
from .bots import CountingBot


def main():
    foreman = BotForeman()
    foreman.attach(CountingBot())
    prompt = foreman.generate_tests("counting.bot")[0].prompt
    for output in ("[1,2,3,4,5]", "[1,2,4,5]", "[1,2,2,3,4,5]",
                   "[1,3,2,4,5]", "[1,2,3,4]", "[2,3,4,5,6]", "Nu stiu"):
        result = foreman.evaluate(prompt, output)[0].to_dict()
        print(f"INPUT: {prompt}\nOUTPUT: {output}")
        for field in ("status", "keep", "omit", "uncertain"):
            print(f"{field.upper()}: {result[field]}")
        print()


if __name__ == "__main__":
    main()
