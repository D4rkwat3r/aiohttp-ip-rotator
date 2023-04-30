from setuptools import setup
from setuptools import find_packages


def readme() -> str:
    with open("README.md", "r") as file:
        return file.read()


def requirements() -> list[str]:
    return ["aiohttp", "aioboto3"]


setup(
    name="aiohttp-ip-rotator",
    version="1.0",
    description="Change the IP address with each http request using the AWS API Gateway.",
    url="https://github.com/D4rkwat3r/aiohttp-ip-rotator",
    long_description=readme(),
    long_description_content_type="text/markdown",
    author_email="ktoya170214@gmail.com",
    packages=find_packages(),
    install_requires=requirements()
)
