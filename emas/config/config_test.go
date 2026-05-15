package config

import "testing"

func TestLoadAutoMigrateDefaultsToEnabledForLocalAndTests(t *testing.T) {
	t.Setenv("EMAS_AUTO_MIGRATE", "")
	t.Setenv("AUTO_MIGRATE", "")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}
	if !cfg.AutoMigrate {
		t.Fatal("AutoMigrate = false, want true by default")
	}
}

func TestLoadAutoMigrateCanBeDisabledForVersionedDeployments(t *testing.T) {
	t.Setenv("EMAS_AUTO_MIGRATE", "false")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}
	if cfg.AutoMigrate {
		t.Fatal("AutoMigrate = true, want false when EMAS_AUTO_MIGRATE=false")
	}
}

func TestLoadAutoMigratePrefersNamespacedFlag(t *testing.T) {
	t.Setenv("AUTO_MIGRATE", "false")
	t.Setenv("EMAS_AUTO_MIGRATE", "true")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}
	if !cfg.AutoMigrate {
		t.Fatal("AutoMigrate = false, want EMAS_AUTO_MIGRATE to override AUTO_MIGRATE")
	}
}
