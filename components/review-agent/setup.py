from setuptools import find_packages, setup

setup(
    name="qingshan-review-agent",
    version="1.1.1",
    description="Local, read-only-first media review agent for Qingshan",
    python_requires=">=3.9",
    install_requires=[
        "numpy>=1.24,<3",
        "onnxruntime>=1.17,<2",
        "opencv-python-headless==4.10.0.84",
        "rapidocr-onnxruntime==1.4.4",
    ],
    packages=find_packages(include=("qingshan_review", "qingshan_review.*")),
    entry_points={"console_scripts": ["qingshan-review=qingshan_review.cli:main"]},
)
