from setuptools import find_packages, setup

setup(
    name="qingshan-review-agent",
    version="1.1.0",
    description="Local, read-only-first media review agent for Qingshan",
    python_requires=">=3.9",
    packages=find_packages(include=("qingshan_review", "qingshan_review.*")),
    entry_points={"console_scripts": ["qingshan-review=qingshan_review.cli:main"]},
)
