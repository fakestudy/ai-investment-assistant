package store

import (
	"context"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

func OpenPostgres(ctx context.Context, databaseURL string) (*gorm.DB, error) {
	db, err := gorm.Open(postgres.Open(databaseURL), &gorm.Config{})
	if err != nil {
		return nil, err
	}
	if err := AutoMigrate(ctx, db); err != nil {
		return nil, err
	}
	return db, nil
}

func AutoMigrate(ctx context.Context, db *gorm.DB) error {
	return db.WithContext(ctx).AutoMigrate(
		&Conversation{},
		&Message{},
		&ToolInvocation{},
	)
}
