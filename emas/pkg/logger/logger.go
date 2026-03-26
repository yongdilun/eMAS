package logger

import (
	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

var Log *zap.Logger

func Init() error {
	cfg := zap.NewProductionConfig()
	cfg.Level = zap.NewAtomicLevelAt(zapcore.InfoLevel)
	l, err := cfg.Build()
	if err != nil {
		return err
	}
	Log = l
	return nil
}

func L() *zap.Logger {
	if Log != nil {
		return Log
	}
	return zap.NewNop()
}
