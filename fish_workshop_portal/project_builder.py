import yaml
from pathlib import Path

def build_node(base_path: Path, node: dict):
    """
    Рекурсивно собирает узел (файл или папку) на основе явного флага is_directory.
    """
    name = node.get("name")
    is_dir = node.get("is_directory", False)
    desc = node.get("description", "")
    children = node.get("children", [])

    if not name:
        return

    current_path = base_path / name

    if is_dir:
        # Это директория
        current_path.mkdir(parents=True, exist_ok=True)
        print(f"📁 Создана папка: {current_path}")
        
        # Рекурсивно собираем всех детей
        for child in children:
            build_node(current_path, child)
    else:
        # Это файл (Dockerfile, .env, main.py и т.д.)
        if current_path.exists():
            return
    
        current_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(current_path, 'w', encoding='utf-8') as f:
            if name.endswith('.py'):
                # Добавляем docstring для Python
                f.write(f'"""\n{desc}\n"""\n\n')
            elif name in ('Dockerfile', '.env', '.gitignore') or name.endswith(('.yml', '.yaml', '.sh')):
                # Добавляем комментарий через #
                f.write(f'# {desc}\n\n')
            else:
                # Обычный текст
                f.write(f'{desc}\n')
                
        print(f"📄 Создан файл:  {current_path}")

def main():
    # Жестко привязываем работу к папке, где лежит этот скрипт (например, TG05)
    script_dir = Path(__file__).parent
    yaml_file = script_dir / "architecture.yaml"
    target_dir = script_dir

    if not yaml_file.exists():
        print(f"❌ Ошибка: Файл {yaml_file} не найден.")
        return

    with open(yaml_file, 'r', encoding='utf-8') as f:
        try:
            architecture = yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"❌ Ошибка парсинга YAML: {e}")
            return

    print("🚀 Начинаю генерацию проекта...\n")

    # Берем корень проекта
    root_node = architecture.get("root")
    if not root_node:
        print("❌ Ошибка: В YAML файле не найден корневой элемент 'root'.")
        return
        
    children = root_node.get("children", [])
    
    # ВАЖНО: Мы не создаем саму папку root.name.
    # Мы сразу перебираем её детей и создаем их ВНУТРИ target_dir
    for child in children:
        build_node(target_dir, child)

    print("\n✅ Структура проекта успешно сгенерирована!")

if __name__ == "__main__":
    main()