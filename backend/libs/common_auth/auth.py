from dataclasses import dataclass
from fastapi import Header


@dataclass
class Actor:
    tenant_id: str
    user_id: str
    role: str


def get_actor(
    x_tenant_id: str = Header(default='11111111-1111-1111-1111-111111111111'),
    x_user_id: str = Header(default='22222222-2222-2222-2222-222222222222'),
    x_role: str = Header(default='admin'),
) -> Actor:
    return Actor(tenant_id=x_tenant_id, user_id=x_user_id, role=x_role)
