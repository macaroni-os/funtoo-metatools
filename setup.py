import setuptools

with open("README.rst", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="funtoo-metatools",
    version="0.5.4",
    author="Daniel Robbins",
    author_email="drobbins@funtoo.org",
    description="Funtoo framework for auto-creation of ebuilds.",
    long_description=long_description,
    long_description_content_type="text/x-rst",
    url="https://code.funtoo.org/bitbucket/users/drobbins/repos/funtoo-metatools/browse",
    scripts=['bin/doit'],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux",
    ],
    python_requires='>=3.7',
    install_requires=[
        'pop>=12',
        'Jinja2',
        'aiohttp',
        'aiodns',
        'tornado>=5'
    ],
    packages=setuptools.find_packages(),
    package_data={ '' : [ '*.tmpl' ] }
)
