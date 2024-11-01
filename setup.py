#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import find_packages, setup

extra = {}

try:
    from trac.util.dist import get_l10n_cmdclass
# i18n is implemented to be optional here
except ImportError:
    pass
else:
    cmdclass = get_l10n_cmdclass()
    if cmdclass:
        extra['cmdclass'] = cmdclass
        extractors = [
            ('**.py', 'python', None),
            ('**/templates/**.html', 'jinja2', None),
        ]
        extra['message_extractors'] = {
            'tractags': extractors,
        }


setup(
    name='TracTags',
    version='0.13',
    packages=find_packages(exclude=['*.tests']),
    package_data={'tractags': [
        'templates/*.html', 'htdocs/js/*.js', 'htdocs/css/*.css',
        'htdocs/images/*.png', 'locale/*/LC_MESSAGES/*.mo',
        'locale/.placeholder']},
    # With acknowledgement to Muness Albrae for the original idea :)
    # With acknowledgement to Dmitry Dianov for input field auto-completion.
    author='Alec Thomas',
    author_email='alec@swapoff.org',
    license='BSD',
    url='https://trac-hacks.org/wiki/TagsPlugin',
    description='Tags plugin for Trac',
    install_requires=['Trac'],
    extras_require={
        'babel': 'Babel>= 0.9.5',
        'tracrpc': 'TracXMLRPC >= 1.1.0',
        'wikiautocomplete': 'WikiAutoComplete >= 1.4dev',
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Plugins',
        'Environment :: Web Environment',
        'Framework :: Trac',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
    ],
    entry_points={'trac.plugins': [
            'tractags = tractags',
            'tractags.xmlrpc = tractags.xmlrpc[tracrpc]',
            'tractags.wikiautocomplete = tractags.wikiautocomplete[wikiautocomplete]',
        ],
    },
    test_suite='tractags.tests.test_suite',
    tests_require=[],
    **extra
)
