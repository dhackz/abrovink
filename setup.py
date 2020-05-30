import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="abrovink", # Replace with your own username
    version="0.0.1",
    author="Albin Vass",
    author_email="albinvass@gmail.com",
    description="Tool to help local ansible playbook development.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/dhackz/abrovink",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
    entry_points = {
        'console_scripts': [
            'abrovink = abrovink.abrovink:main',                  
        ],              
    },
    install_requires = [
        'pyyaml'
    ],
)
