"""initial schema

Revision ID: 0001
Revises: 
"""
from alembic import op
import sqlalchemy as sa
import geoalchemy2


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")   # geometry columns need it
    op.create_table('fleets',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('drivers',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('fleet_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('consent_given_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['fleet_id'], ['fleets.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_drivers_fleet_id'), 'drivers', ['fleet_id'], unique=False)
    op.create_table('vehicles',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('fleet_id', sa.UUID(), nullable=False),
    sa.Column('registration', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('delivery', 'truck', 'ambulance', 'school_bus', 'other')", name='ck_vehicle_kind'),
    sa.ForeignKeyConstraint(['fleet_id'], ['fleets.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('fleet_id', 'registration', name='uq_vehicle_registration_per_fleet')
    )
    op.create_index(op.f('ix_vehicles_fleet_id'), 'vehicles', ['fleet_id'], unique=False)
    op.create_table('trips',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('fleet_id', sa.UUID(), nullable=False),
    sa.Column('driver_id', sa.UUID(), nullable=True),
    sa.Column('vehicle_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('route', geoalchemy2.types.Geometry(geometry_type='LINESTRING', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('route_length_m', sa.Float(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('active', 'ended')", name='ck_trip_status'),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ),
    sa.ForeignKeyConstraint(['fleet_id'], ['fleets.id'], ),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_trips_driver_id'), 'trips', ['driver_id'], unique=False)
    op.create_index('ix_trips_fleet_started', 'trips', ['fleet_id', 'started_at'], unique=False)
    op.create_index('ix_trips_route', 'trips', ['route'], unique=False, postgresql_using='gist')
    op.create_index(op.f('ix_trips_vehicle_id'), 'trips', ['vehicle_id'], unique=False)
    op.create_table('deviations',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('trip_id', sa.String(length=40), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('location', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('deviation_m', sa.Float(), nullable=True),
    sa.Column('reason', sa.String(length=16), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_deviations_location', 'deviations', ['location'], unique=False, postgresql_using='gist')
    op.create_index(op.f('ix_deviations_trip_id'), 'deviations', ['trip_id'], unique=False)
    op.create_table('stops',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('trip_id', sa.String(length=40), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=True),
    sa.Column('location', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('arrived_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('trip_id', 'seq', name='uq_stop_seq_per_trip')
    )
    op.create_index(op.f('ix_stops_trip_id'), 'stops', ['trip_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_stops_trip_id'), table_name='stops')
    op.drop_table('stops')
    op.drop_index(op.f('ix_deviations_trip_id'), table_name='deviations')
    op.drop_index('ix_deviations_location', table_name='deviations', postgresql_using='gist')
    op.drop_table('deviations')
    op.drop_index(op.f('ix_trips_vehicle_id'), table_name='trips')
    op.drop_index('ix_trips_route', table_name='trips', postgresql_using='gist')
    op.drop_index('ix_trips_fleet_started', table_name='trips')
    op.drop_index(op.f('ix_trips_driver_id'), table_name='trips')
    op.drop_table('trips')
    op.drop_index(op.f('ix_vehicles_fleet_id'), table_name='vehicles')
    op.drop_table('vehicles')
    op.drop_index(op.f('ix_drivers_fleet_id'), table_name='drivers')
    op.drop_table('drivers')
    op.drop_table('fleets')
