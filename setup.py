from setuptools import setup
setup(
    name='tp-version-switch',
    version='0.0.1',
    entry_points={
        'console_scripts': [
            'tp-version-switch=switcher:main'
        ]
    }
)
