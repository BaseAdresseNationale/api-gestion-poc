import pytest

from ban.auth import models
from ban.tests.factories import UserFactory, ClientFactory


def test_session_can_be_created_with_a_user():
    user = UserFactory()
    session = models.Session.create(user=user, contributor_type='admin')
    assert session.user == user
    assert session.serialize() == {
        'id': session.pk,
        'user': user.username,
        'client': None,
        'contributor_type': 'admin'
    }


def test_session_can_be_created_with_a_client():
    client = ClientFactory()
    session = models.Session.create(client=client, contributor_type='admin')
    assert session.client == client
    assert session.serialize() == {
        'id': session.pk,
        'user': None,
        'client': client.name,
        'contributor_type': 'admin'
    }


def test_session_should_have_either_a_client_or_a_user():
    with pytest.raises(ValueError):
        models.Session.create()
