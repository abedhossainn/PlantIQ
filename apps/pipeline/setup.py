"""
PlantIQ Pipeline Package Setup
Human-in-the-Loop document ingestion and validation system
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README for long description
readme_path = Path(__file__).parent.parent.parent / "README.md"
long_description = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

# Read requirements
requirements_path = Path(__file__).parent / "requirements.txt"
requirements = []
if requirements_path.exists():
    requirements = [
        line.strip() 
        for line in requirements_path.read_text(encoding="utf-8").split('\n')
        if line.strip() and not line.startswith('#')
    ]

setup(
    name="plantiq-pipeline",
    version="0.1.0",
    author="PlantIQ Team",
    author_email="",
    description="Human-in-the-Loop document ingestion and validation pipeline",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/abedhossainn/PlantIQ",
    packages=find_packages(where=".", include=["src", "src.*"]),
    package_dir={"": "."},
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.10",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "pytest-cov>=4.1.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.5.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "plantiq-pipeline=src.cli.hitl_pipeline:main",
            "plantiq-reformat=src.cli.text_reformatter:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
