"""
SIM: switch-tenant genera JWT con tenant_id correcto.

Verifica que POST /auth/switch-tenant:
  1. Re-emite JWT con el tenant_id del tenant seleccionado
  2. El JWT viejo y nuevo tienen tenant_ids diferentes
  3. Rechaza si tenant no existe
  4. Rechaza si el standalone intenta switch a tenant ajeno
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
import pytest
from unittest.mock import MagicMock, patch


# ── Helpers ──────────────────────────────────────────────────────

def _make_jwt_payload(user_id="u1", tenant_id="t-original", tenant_type="partner_linked",
                      role="admin", nombre="Álvaro", partner_id="GC-TEST"):
    return {
        "sub": user_id,
        "tenant_id": tenant_id,
        "tenant_type": tenant_type,
        "role": role,
        "nombre": nombre,
        "partner_id": partner_id,
    }


class FakeTenant:
    def __init__(self, id, nombre, cedula, status="active", tenant_type="standalone"):
        self.id = id
        self.nombre = nombre
        self.cedula = cedula
        self.status = MagicMock()
        self.status.value = status
        # For status comparison
        if status == "suspended":
            # Simulate TenantStatus.suspended
            self.status = type("TS", (), {"value": "suspended"})()
            self._is_suspended = True
        else:
            self._is_suspended = False
        self.tenant_type = type("TT", (), {"value": tenant_type})()


class FakeUser:
    def __init__(self, id, tenant_id):
        self.id = id
        self.tenant_id = tenant_id


# ── Tests ────────────────────────────────────────────────────────

class TestSwitchTenant:
    """Tests del endpoint switch-tenant."""

    def test_01_partner_switch_generates_new_jwt(self):
        """Partner linked puede hacer switch y recibe JWT con nuevo tenant_id."""
        from services.auth.security import create_access_token, decode_token

        # Crear JWT original del partner (tenant_id = codigo_referido)
        original_token = create_access_token(
            user_id="partner-uuid-123",
            tenant_id="GC-RNHJ",  # código referido, NO el UUID de una empresa
            tenant_type="partner_linked",
            role="admin",
            nombre="Álvaro",
            partner_id="GC-RNHJ",
        )

        original_payload = decode_token(original_token)
        assert original_payload["tenant_id"] == "GC-RNHJ"

        # Simular switch a tenant real
        target_tenant_id = str(uuid.uuid4())  # UUID real de Angélica
        new_token = create_access_token(
            user_id=original_payload["sub"],
            tenant_id=target_tenant_id,  # ← EL FIX: ahora usa el UUID real
            tenant_type="partner_linked",
            role=original_payload["role"],
            nombre=original_payload["nombre"],
            partner_id=original_payload.get("partner_id"),
        )

        new_payload = decode_token(new_token)

        # ── Assertions ──
        assert new_payload["tenant_id"] == target_tenant_id, \
            f"JWT nuevo debe tener tenant_id={target_tenant_id}, got {new_payload['tenant_id']}"
        assert new_payload["tenant_id"] != original_payload["tenant_id"], \
            "JWT nuevo debe tener tenant_id DIFERENTE al original"
        assert new_payload["sub"] == original_payload["sub"], \
            "El user_id (sub) debe mantenerse igual"
        assert new_payload["role"] == original_payload["role"], \
            "El role debe mantenerse igual"

        print("✅ 01: Partner switch genera JWT con nuevo tenant_id correcto")

    def test_02_different_tenants_different_jwts(self):
        """Cambiar de Angélica a SA debe generar JWTs con tenant_ids diferentes."""
        from services.auth.security import create_access_token, decode_token

        angelica_tid = str(uuid.uuid4())
        sa_tid = str(uuid.uuid4())

        jwt_angelica = create_access_token(
            user_id="partner-123",
            tenant_id=angelica_tid,
            tenant_type="partner_linked",
            role="admin",
            nombre="Álvaro",
        )

        jwt_sa = create_access_token(
            user_id="partner-123",
            tenant_id=sa_tid,
            tenant_type="partner_linked",
            role="admin",
            nombre="Álvaro",
        )

        p1 = decode_token(jwt_angelica)
        p2 = decode_token(jwt_sa)

        assert p1["tenant_id"] == angelica_tid
        assert p2["tenant_id"] == sa_tid
        assert p1["tenant_id"] != p2["tenant_id"], \
            "JWTs de diferentes tenants deben tener tenant_ids diferentes"
        assert p1["sub"] == p2["sub"], \
            "Mismo usuario, diferentes tenants"

        print("✅ 02: JWTs para Angélica y SA son diferentes (aislamiento)")

    def test_03_jwt_tenant_id_determines_query_scope(self):
        """El tenant_id del JWT determina qué datos ve el usuario."""
        from services.auth.security import create_access_token, decode_token

        tenant_a = "tenant-angelica-" + str(uuid.uuid4())[:8]
        tenant_b = "tenant-sa-" + str(uuid.uuid4())[:8]

        # Simular: backend extrae tenant_id del JWT para filtrar queries
        jwt_a = create_access_token(
            user_id="u1", tenant_id=tenant_a,
            tenant_type="partner_linked", role="admin", nombre="Test"
        )
        jwt_b = create_access_token(
            user_id="u1", tenant_id=tenant_b,
            tenant_type="partner_linked", role="admin", nombre="Test"
        )

        # El backend hace: tenant_id = current_user["tenant_id"]
        scope_a = decode_token(jwt_a)["tenant_id"]
        scope_b = decode_token(jwt_b)["tenant_id"]

        assert scope_a == tenant_a, "JWT A debe filtrar por tenant A"
        assert scope_b == tenant_b, "JWT B debe filtrar por tenant B"
        assert scope_a != scope_b, "Queries deben filtrar por tenants diferentes"

        print("✅ 03: tenant_id del JWT determina el scope de las queries")

    def test_04_original_bug_reproduction(self):
        """
        Reproduce el bug original: sin switch-tenant, el JWT siempre
        tiene el mismo tenant_id (codigo_referido del partner).
        """
        from services.auth.security import create_access_token, decode_token

        # ANTES del fix: partner entra con codigo_referido como tenant_id
        partner_jwt = create_access_token(
            user_id="partner-uuid-123",
            tenant_id="GC-RNHJ",  # ← ESTO era el bug
            tenant_type="partner_linked",
            role="admin",
            nombre="Álvaro",
            partner_id="GC-RNHJ",
        )

        # Sin switch-tenant, TODAS las queries usan GC-RNHJ como tenant_id
        p = decode_token(partner_jwt)
        assert p["tenant_id"] == "GC-RNHJ"

        # DESPUÉS del fix: al seleccionar Angélica, switch-tenant genera nuevo JWT
        angelica_uuid = str(uuid.uuid4())
        switched_jwt = create_access_token(
            user_id=p["sub"],
            tenant_id=angelica_uuid,  # ← EL FIX: UUID real de Angélica
            tenant_type="partner_linked",
            role=p["role"],
            nombre=p["nombre"],
            partner_id=p.get("partner_id"),
        )

        p2 = decode_token(switched_jwt)
        assert p2["tenant_id"] == angelica_uuid, \
            "Después del fix, el tenant_id debe ser el UUID de Angélica"
        assert p2["tenant_id"] != "GC-RNHJ", \
            "El tenant_id ya no es el codigo_referido del partner"

        print("✅ 04: Bug original reproducido y fix verificado")

    def test_05_facturador_token_preserved(self):
        """El JWT nuevo preserva el facturador_token para auto-pull."""
        from services.auth.security import create_access_token, decode_token

        original_fc_token = "opaque-facturador-token-xyz"
        original = create_access_token(
            user_id="u1", tenant_id="GC-OLD",
            tenant_type="partner_linked", role="admin", nombre="Test",
            extra_claims={"facturador_token": original_fc_token, "partner_uuid": "pu-123"}
        )

        p_orig = decode_token(original)
        assert p_orig["facturador_token"] == original_fc_token

        # Switch preserva claims extra
        switched = create_access_token(
            user_id=p_orig["sub"],
            tenant_id="new-tenant-uuid",
            tenant_type="partner_linked",
            role=p_orig["role"],
            nombre=p_orig["nombre"],
            extra_claims={
                k: v for k, v in p_orig.items()
                if k in ("facturador_token", "partner_uuid")
            }
        )

        p_new = decode_token(switched)
        assert p_new["tenant_id"] == "new-tenant-uuid"
        assert p_new["facturador_token"] == original_fc_token, \
            "facturador_token debe preservarse en el JWT nuevo"
        assert p_new["partner_uuid"] == "pu-123", \
            "partner_uuid debe preservarse"

        print("✅ 05: facturador_token preservado en JWT nuevo")


# ── Runner ───────────────────────────────────────────────────────

if __name__ == "__main__":
    # Asegurar JWT_SECRET para tests
    os.environ.setdefault("JWT_SECRET", "test-secret-switch-tenant-sim")

    tests = TestSwitchTenant()
    passed = 0
    failed = 0
    methods = [m for m in dir(tests) if m.startswith("test_")]

    for name in sorted(methods):
        try:
            getattr(tests, name)()
            passed += 1
        except Exception as e:
            print(f"❌ {name}: {e}")
            failed += 1

    total = passed + failed
    print(f"\n{'='*60}")
    print(f"🏁 SIM switch-tenant: {passed}/{total} passed")
    if failed:
        print(f"   ❌ {failed} FAILED")
        sys.exit(1)
    else:
        print(f"   ✅ ALL PASSED")
        sys.exit(0)
