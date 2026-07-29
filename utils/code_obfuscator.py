import re


class CodeObfuscator:

    @classmethod
    def deobfuscate_code(cls, obfuscated_code: str) -> str:
        cleaned = obfuscated_code.replace('_', '')

        result = re.sub(r'[^0-9]', '', cleaned)

        return result

    @classmethod
    def is_valid_code_format(cls, code: str) -> bool:
        return '_' in code

    @classmethod
    def generate_examples(cls, code: str) -> list:
        if not code or not code.isdigit():
            return []

        examples = []

        for i in range(1, len(code)):
            example = code[:i] + '_' + code[i:]
            examples.append(example)

        examples.append('_' + code)
        examples.append(code + '_')

        if len(code) >= 3:
            examples.append(code[:2] + '_' + code[2:4] + '_' + code[4:])

        return examples[:5]


if __name__ == "__main__":
    obfuscator = CodeObfuscator()

    test_codes = ["12345", "67890", "11111"]

    print("=== Тестирование системы обфускации (только подчеркивания) ===\n")

    for original in test_codes:
        print(f"Оригинальный код: {original}")

        examples = obfuscator.generate_examples(original)

        for i, obfuscated in enumerate(examples):
            deobfuscated = obfuscator.deobfuscate_code(obfuscated)
            is_valid = obfuscator.is_valid_code_format(obfuscated)

            print(f"  Пример {i+1}: {obfuscated}")
            print(f"  Деобфускированный: {deobfuscated}")
            print(f"  Валидный формат: {is_valid}")
            print(f"  Корректность: {'✅' if deobfuscated == original else '❌'}")
            print()

        print("-" * 50)

    user_examples = ["65_972", "1_2345", "123_45", "_12345", "12345_"]
    print("\n=== Тестирование пользовательских примеров ===\n")

    for example in user_examples:
        deobfuscated = obfuscator.deobfuscate_code(example)
        is_valid = obfuscator.is_valid_code_format(example)

        print(f"Пример: {example}")
        print(f"Деобфускированный: {deobfuscated}")
        print(f"Валидный формат: {is_valid}")
        print()
