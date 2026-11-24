from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import os

# ============================================================
# CONFIGURATION
# ============================================================

PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_ZIP = PROJECT_DIR.parent / f"{PROJECT_DIR.name}_clean.zip"

# Entire directories to exclude
EXCLUDED_DIRS = {
    ".venv",
    "venv",
    "env",
    ".env",
    "node_modules",
    "__pycache__",
    ".git",
    ".github",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "FraudShield-Dataset",
    ".tox",
    ".cache",
    "dist",
    "build",
    "coverage",
    ".coverage",
    "htmlcov",
    ".next",
    ".nuxt",
    ".parcel-cache",
    ".turbo",
    "tmp",
    "temp",
    "logs",
}

# Individual filenames to exclude
EXCLUDED_FILES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    ".coverage",
    "npm-debug.log",
    "yarn-debug.log",
    "yarn-error.log",
    "pnpm-debug.log",
}

# File extensions to exclude
EXCLUDED_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".log",
    ".tmp",
    ".temp",
    ".bak",
    ".swp",
    ".swo",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
}

# Optional: files containing secrets/local configuration
# Add/remove names depending on what you want inside the ZIP.
SECRET_FILES = {
    ".env",
    ".env.local",
    ".env.development.local",
    ".env.production.local",
    ".env.test.local",
}


def should_exclude(path: Path) -> bool:
    """Return True if the path should not be included in the ZIP."""

    relative_path = path.relative_to(PROJECT_DIR)

    # Exclude if any parent directory is unwanted
    if any(part in EXCLUDED_DIRS for part in relative_path.parts[:-1]):
        return True

    # Exclude directory itself
    if path.is_dir() and path.name in EXCLUDED_DIRS:
        return True

    # Exclude specific filenames
    if path.name in EXCLUDED_FILES:
        return True

    # Exclude secret environment files
    if path.name in SECRET_FILES:
        return True

    # Exclude unwanted extensions
    if path.is_file() and path.suffix.lower() in EXCLUDED_EXTENSIONS:
        return True

    # Avoid accidentally adding the generated ZIP itself
    if path.resolve() == OUTPUT_ZIP.resolve():
        return True

    return False


def create_clean_zip():
    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    included_files = 0
    skipped_files = 0

    print(f"\nProject : {PROJECT_DIR}")
    print(f"Output  : {OUTPUT_ZIP}")
    print("\nCreating clean ZIP...\n")

    with ZipFile(
        OUTPUT_ZIP,
        "w",
        compression=ZIP_DEFLATED,
        compresslevel=9,
    ) as zip_file:

        for root, dirs, files in os.walk(PROJECT_DIR):
            root_path = Path(root)

            # Prevent os.walk from even entering excluded directories
            dirs[:] = [
                directory
                for directory in dirs
                if not should_exclude(root_path / directory)
            ]

            for filename in files:
                file_path = root_path / filename

                if should_exclude(file_path):
                    skipped_files += 1
                    continue

                relative_path = file_path.relative_to(PROJECT_DIR)

                try:
                    zip_file.write(
                        file_path,
                        arcname=relative_path,
                    )

                    included_files += 1
                    print(f"[ADD]  {relative_path}")

                except PermissionError:
                    skipped_files += 1
                    print(f"[SKIP - Permission denied] {relative_path}")

                except OSError as error:
                    skipped_files += 1
                    print(f"[SKIP - {error}] {relative_path}")

    size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)

    print("\n" + "=" * 60)
    print("CLEAN ZIP CREATED SUCCESSFULLY")
    print("=" * 60)
    print(f"Files included : {included_files}")
    print(f"Files skipped  : {skipped_files}")
    print(f"ZIP size       : {size_mb:.2f} MB")
    print(f"Saved at       : {OUTPUT_ZIP}")
    print("=" * 60)


if __name__ == "__main__":
    create_clean_zip()