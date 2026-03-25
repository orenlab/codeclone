# mypy: ignore-errors

from pkg.a import ServiceA, transform_shared_a
from pkg.b import transform_shared_b

SERVICE = ServiceA()
RESULT_A = transform_shared_a([1, 2, 3])
RESULT_B = transform_shared_b([1, 2, 3])
RESULT_C = SERVICE.compute([1, 2, 3])
