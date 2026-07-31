"""Importable distribution whose name carries capital letters.

Rename twin of the ``example`` distribution, mutated on the axis that the
classifier must be blind to: the package name's capitalization. Module
identity keys preserve case, so a classifier that lowercases the module path
before consulting the registry stops recognizing this tree as a distributed
package and flips its ``testing`` subpackage to test-kind.
"""
