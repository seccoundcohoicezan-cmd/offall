"""Clear provider base_url values that are not http(s) URLs.

Some users pasted an API key into the Base URL field, which stored it in plain
text and broke every request. Such values are removed (keys live encrypted in
provider_keys; nothing else references base_url).

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE providers SET base_url = NULL "
            "WHERE base_url IS NOT NULL "
            "AND lower(base_url) NOT LIKE 'http://%' AND lower(base_url) NOT LIKE 'https://%'"
        )
    )


def downgrade() -> None:
    pass  # cleared values were invalid (and secrets); nothing to restore
