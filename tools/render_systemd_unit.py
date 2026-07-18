from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = PROJECT_ROOT / 'systemd/macropad.service.in'
OUTPUT_PATH = PROJECT_ROOT / 'tmp/macropad.service'


def validate_path(path: str) -> None:
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        raise ValueError('systemd paths cannot contain control characters')


def escape_path(path: str) -> str:
    validate_path(path)
    return path.replace('\\', '\\\\').replace('%', '%%')


def quote_exec_path(path: str) -> str:
    escaped = escape_path(path).replace('"', '\\"').replace('$', '$$')
    return f'"{escaped}"'


def render_service(template: str, project_root: Path) -> str:
    replacements = {
        '@WORKING_DIRECTORY@': escape_path(str(project_root)),
        '@EXECUTABLE@': quote_exec_path(str(project_root / '.venv/bin/macropad')),
    }
    rendered = template
    for placeholder, value in replacements.items():
        if rendered.count(placeholder) != 1:
            raise ValueError(f'template must contain one {placeholder} placeholder')
        rendered = rendered.replace(placeholder, value)
    return rendered


def main() -> None:
    rendered = render_service(TEMPLATE_PATH.read_text(), PROJECT_ROOT)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(rendered)


if __name__ == '__main__':
    main()
