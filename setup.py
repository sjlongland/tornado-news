#!/usr/bin/python
from setuptools import setup
from tornadonews import __version__

setup(name = 'tornadonews',
	version = __version__,
        description = 'Tornado News: a simple news aggregator',
	packages = [
            'tornadonews',
        ],
        entry_points = {
            'console_scripts': [
                'tornadonews=tornadonews.tornadonews:main',
            ],
        },
)
