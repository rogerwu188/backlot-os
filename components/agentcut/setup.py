from setuptools import find_packages, setup


setup(
    name="agentcut",
    version="0.9.20",
    description="Headless, JSON-driven FFmpeg editing engine for AI agents",
    packages=find_packages(include=["agentcut", "agentcut.*"]),
    package_data={"agentcut": ["vendor/**/*", "templates/**/*", "shot_recipes/*"]},
    python_requires=">=3.10",
    entry_points={"console_scripts": ["agentcut=agentcut.cli:main"]},
)
