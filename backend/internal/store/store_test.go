package store

import (
	"os"
	"strings"
	"testing"
)

func TestProductionStoreDoesNotDependOnSQLite(t *testing.T) {
	source, err := os.ReadFile("store.go")
	if err != nil {
		t.Fatalf("ReadFile(store.go) error = %v", err)
	}

	content := string(source)
	forbidden := []string{
		"gorm.io/driver/sqlite",
		"OpenSQLite",
	}
	for _, value := range forbidden {
		if strings.Contains(content, value) {
			t.Fatalf("production store.go must not contain %q; keep SQLite helpers in test-only files", value)
		}
	}
}
