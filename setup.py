from setuptools import setup, find_packages

setup(
    name='linkedin-resume-agent',
    version='2.0.0',
    packages=find_packages(),
    install_requires=[
        'requests>=2.31.0',
        'PyYAML>=6.0.1',
        'beautifulsoup4>=4.12.3',
        'lxml>=5.1.0',
        'PyPDF2>=3.0.1',
    ],
    entry_points={
        'console_scripts': [
            'linkedin-resume-agent=src.main:main',
        ],
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.9',
)