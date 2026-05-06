"""Tests for database analyser Layer 1 scanner."""

from __future__ import annotations

import textwrap

import pytest

from app.services.db_analyser.layer1_scanner import Layer1Scanner


def _write(tmp_path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    return str(p)


def test_n_plus_one_django_loop_filter_inner_query(tmp_path):
    path = _write(
        tmp_path,
        "views.py",
        """
        from django.db import models
        class User(models.Model):
            pass
        class Order(models.Model):
            pass
        def view(request):
            for user in User.objects.filter(is_active=True):
                Order.objects.filter(user=user).first()
        """,
    )
    root = str(tmp_path)
    res = Layer1Scanner(root, [path]).scan()
    n1 = [f for f in res.findings if f.category == "n_plus_one"]
    assert n1, "expected n_plus_one finding"
    assert n1[0].severity in ("HIGH", "CRITICAL")


def test_raw_sql_fstring_injection(tmp_path):
    path = _write(
        tmp_path,
        "bad_sql.py",
        """
        def bad(request):
            uid = request.GET['id']
            sql = f"SELECT * FROM users WHERE id = {uid}"
            cursor.execute(sql)
        """,
    )
    res = Layer1Scanner(str(tmp_path), [path]).scan()
    inj = [f for f in res.findings if f.category == "raw_sql_injection"]
    assert inj
    assert inj[0].severity == "CRITICAL"


def test_all_with_python_side_filter(tmp_path):
    path = _write(
        tmp_path,
        "filters.py",
        """
        from django.db import models
        class User(models.Model):
            is_active = models.BooleanField()
        def load():
            active_users = [u for u in User.objects.all() if u.is_active]
            return active_users
        """,
    )
    res = Layer1Scanner(str(tmp_path), [path]).scan()
    found = [f for f in res.findings if f.category == "orm_all_no_filter"]
    assert found


def test_transaction_missing_atomic_multi_table(tmp_path):
    path = _write(
        tmp_path,
        "writes.py",
        """
        from django.db import models
        class Order(models.Model):
            pass
        class Inventory(models.Model):
            pass
        def create_order():
            Order.objects.create()
            Inventory.objects.filter(id=1).update(quantity=1)
        """,
    )
    res = Layer1Scanner(str(tmp_path), [path]).scan()
    tx = [f for f in res.findings if f.category == "transaction_missing_atomic"]
    assert tx


def test_orm_framework_detected_from_imports(tmp_path):
    path = _write(
        tmp_path,
        "models_file.py",
        """
        from django.db import models
        class M(models.Model):
            name = models.CharField(max_length=10)
        """,
    )
    res = Layer1Scanner(str(tmp_path), [path]).scan()
    assert "django" in res.orm_frameworks_detected


def test_no_false_positive_select_related_in_loop(tmp_path):
    path = _write(
        tmp_path,
        "ok.py",
        """
        from django.db import models
        class User(models.Model):
            pass
        class Profile(models.Model):
            pass
        def ok_view():
            for user in User.objects.select_related('profile').all():
                print(user.profile.bio)
        """,
    )
    res = Layer1Scanner(str(tmp_path), [path]).scan()
    bad = [
        f
        for f in res.findings
        if f.category in ("orm_missing_select_related", "n_plus_one")
    ]
    assert not bad, bad
