import random

CYRILLIC_TO_LATIN = {
    'а': ['a'],
    'А': ['A'],
    'е': ['e'],
    'Е': ['E'],
    'о': ['o'],
    'О': ['O'],
    'р': ['p'],
    'Р': ['P'],
    'у': ['y'],
    'х': ['x'],
    'Х': ['X'],
    'с': ['c'],
    'С': ['C'],
    'К': ['K'],
    'М': ['M'],
    'Т': ['T'],
    'ё': ['e']
}

def substitute_cyrillic_to_latin(text: str, substitution_rate: float = 0.3) -> str:
    if not text:
        return text
    result = []
    for char in text:
        if char in CYRILLIC_TO_LATIN:
            if random.random() < substitution_rate:
                replacements = CYRILLIC_TO_LATIN[char]
                if replacements:
                    replacement = random.choice(replacements)
                    result.append(replacement)
                else:
                    result.append(char)
            else:
                result.append(char)
        else:
            result.append(char)
    return ''.join(result)

def has_cyrillic_characters(text: str) -> bool:
    if not text:
        return False
    for char in text:
        if char in CYRILLIC_TO_LATIN:
            return True
    return False

def apply_cyrillic_substitution(text: str, enabled: bool = True, rate: float = 0.3) -> str:
    if not enabled or not text:
        return text
    if not has_cyrillic_characters(text):
        return text

    if '<' in text and '>' in text:
        import re

        html_tags = []
        for match in re.finditer(r'<[^>]+>', text):
            html_tags.append((match.start(), match.end()))

        result = []
        current_pos = 0

        for start, end in html_tags:
            if current_pos < start:
                before_tag = text[current_pos:start]
                result.append(substitute_cyrillic_to_latin(before_tag, rate))

            result.append(text[start:end])
            current_pos = end

        if current_pos < len(text):
            after_tags = text[current_pos:]
            result.append(substitute_cyrillic_to_latin(after_tags, rate))

        return ''.join(result)
    else:
        return substitute_cyrillic_to_latin(text, rate)

if __name__ == "__main__":
    test_texts = [
        "Привет, как дела?",
        "Это тестовое сообщение",
        "Hello world!",
        "Смешанный текст with English",
        "БОЛЬШИЕ БУКВЫ тоже работают",
        "<b>Жирный текст</b>",
        "<i>Курсивный текст</i>",
        "<u>Подчеркнутый</u> и <b>жирный</b> текст",
        "Обычный текст с <code>кодом</code> внутри",
        "Сложный <b>жирный</b> и <i>курсивный</i> текст"
    ]
    print("Примеры работы подмены кириллицы:")
    print("-" * 60)
    for text in test_texts:
        substituted = apply_cyrillic_substitution(text, enabled=True, rate=0.4)
        print(f"Исходный: {text}")
        print(f"Замена:   {substituted}")
        print()
