// Package main: canonical BOM specification driving Formula, ProcessStepMaterial, and ProductBOM.
// Consistency rule: Sum(ProcessStepMaterial input qty per material/product) == Formula ingredient qty.

package main

import "emas/internal/domain"

// bomSpecEntry defines one step-level material input or output.
// Formula is derived by aggregating inputs per product; ProcessStepMaterial uses each entry directly.
type bomSpecEntry struct {
	ProductID      string  // parent product (P-001, etc.)
	StepID         string  // process step that consumes (input) or produces (output)
	MaterialID     *string // for raw material component
	ProductIDComp  *string // for sub-assembly component (avoids name clash with ProductID)
	Qty            float64
	Unit           string
	Role           string // input | output
	LeadTimeHours  int
	Source         string // buy | make
	ScrapRate      float64
	FormulaID      string // F-001, etc.
	FormulaName    string
	IngredientID   string // for Formula
}

// bomSpec returns the canonical BOM definitions. P-001: MAT-005 fixed to 1 L on Step 4 only.
func bomSpec() []bomSpecEntry {
	mat := func(s string) *string { return &s }
	prod := func(s string) *string { return &s }
	return []bomSpecEntry{
		// P-001: MAT-001, MAT-002 → Step 1; MAT-005 → Step 4 only (1 L); P-007, P-008 → Step 5; Output → Step 5
		{ProductID: "P-001", StepID: "STP-P001-1", MaterialID: mat("MAT-001"), Qty: 2.5, Unit: "kg", Role: domain.ProcessStepMaterialRoleInput, LeadTimeHours: 0, Source: domain.IngredientSourceBuy, FormulaID: "F-001", FormulaName: "Valve Body Mix", IngredientID: "ING-F001-MAT001"},
		{ProductID: "P-001", StepID: "STP-P001-1", MaterialID: mat("MAT-002"), Qty: 0.08, Unit: "kg", Role: domain.ProcessStepMaterialRoleInput, LeadTimeHours: 24, Source: domain.IngredientSourceBuy, FormulaID: "F-001", FormulaName: "Valve Body Mix", IngredientID: "ING-F001-MAT002"},
		{ProductID: "P-001", StepID: "STP-P001-4", MaterialID: mat("MAT-005"), Qty: 1.0, Unit: "L", Role: domain.ProcessStepMaterialRoleInput, LeadTimeHours: 48, Source: domain.IngredientSourceBuy, FormulaID: "F-001", FormulaName: "Valve Body Mix", IngredientID: "ING-F001-MAT005"},
		{ProductID: "P-001", StepID: "STP-P001-5", ProductIDComp: prod("P-007"), Qty: 1, Unit: "set", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceMake, ScrapRate: 0.02, FormulaID: "F-001", FormulaName: "Valve Body Mix", IngredientID: "ING-F001-P007"},
		{ProductID: "P-001", StepID: "STP-P001-5", ProductIDComp: prod("P-008"), Qty: 1, Unit: "pcs", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceMake, ScrapRate: 0.01, FormulaID: "F-001", FormulaName: "Valve Body Mix", IngredientID: "ING-F001-P008"},
		{ProductID: "P-001", StepID: "STP-P001-5", ProductIDComp: prod("P-001"), Qty: 1, Unit: "pcs", Role: domain.ProcessStepMaterialRoleOutput, FormulaID: "F-001", FormulaName: "Valve Body Mix", IngredientID: ""},
		// P-002
		{ProductID: "P-002", StepID: "STP-P002-1", MaterialID: mat("MAT-003"), Qty: 3.2, Unit: "kg", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceBuy, FormulaID: "F-002", FormulaName: "Gear Set Steel Mix", IngredientID: "ING-F002-MAT003"},
		{ProductID: "P-002", StepID: "STP-P002-1", MaterialID: mat("MAT-006"), Qty: 0.5, Unit: "L", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceBuy, FormulaID: "F-002", FormulaName: "Gear Set Steel Mix", IngredientID: "ING-F002-MAT006"},
		{ProductID: "P-002", StepID: "STP-P002-3", ProductIDComp: prod("P-002"), Qty: 1, Unit: "set", Role: domain.ProcessStepMaterialRoleOutput, FormulaID: "F-002", FormulaName: "Gear Set Steel Mix", IngredientID: ""},
		// P-003
		{ProductID: "P-003", StepID: "STP-P003-1", MaterialID: mat("MAT-004"), Qty: 4.0, Unit: "kg", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceBuy, FormulaID: "F-003", FormulaName: "Cylinder Rod BOM", IngredientID: "ING-F003-MAT004"},
		{ProductID: "P-003", StepID: "STP-P003-2", MaterialID: mat("MAT-007"), Qty: 0.3, Unit: "L", Role: domain.ProcessStepMaterialRoleInput, LeadTimeHours: 48, Source: domain.IngredientSourceBuy, FormulaID: "F-003", FormulaName: "Cylinder Rod BOM", IngredientID: "ING-F003-MAT007"},
		{ProductID: "P-003", StepID: "STP-P003-3", ProductIDComp: prod("P-003"), Qty: 1, Unit: "pcs", Role: domain.ProcessStepMaterialRoleOutput, FormulaID: "F-003", FormulaName: "Cylinder Rod BOM", IngredientID: ""},
		// P-004
		{ProductID: "P-004", StepID: "STP-P004-1", MaterialID: mat("MAT-008"), Qty: 3.5, Unit: "kg", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceBuy, FormulaID: "F-004", FormulaName: "Motor Housing BOM", IngredientID: "ING-F004-MAT008"},
		{ProductID: "P-004", StepID: "STP-P004-1", MaterialID: mat("MAT-012"), Qty: 0.15, Unit: "kg", Role: domain.ProcessStepMaterialRoleInput, LeadTimeHours: 24, Source: domain.IngredientSourceBuy, FormulaID: "F-004", FormulaName: "Motor Housing BOM", IngredientID: "ING-F004-MAT012"},
		{ProductID: "P-004", StepID: "STP-P004-4", ProductIDComp: prod("P-007"), Qty: 1, Unit: "set", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceMake, ScrapRate: 0.02, FormulaID: "F-004", FormulaName: "Motor Housing BOM", IngredientID: "ING-F004-P007"},
		{ProductID: "P-004", StepID: "STP-P004-4", ProductIDComp: prod("P-004"), Qty: 1, Unit: "pcs", Role: domain.ProcessStepMaterialRoleOutput, FormulaID: "F-004", FormulaName: "Motor Housing BOM", IngredientID: ""},
		// P-005
		{ProductID: "P-005", StepID: "STP-P005-1", MaterialID: mat("MAT-008"), Qty: 1.2, Unit: "kg", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceBuy, FormulaID: "F-005", FormulaName: "Control Bracket BOM", IngredientID: "ING-F005-MAT008"},
		{ProductID: "P-005", StepID: "STP-P005-1", MaterialID: mat("MAT-010"), Qty: 4, Unit: "pcs", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceBuy, FormulaID: "F-005", FormulaName: "Control Bracket BOM", IngredientID: "ING-F005-MAT010"},
		{ProductID: "P-005", StepID: "STP-P005-1", MaterialID: mat("MAT-012"), Qty: 0.2, Unit: "kg", Role: domain.ProcessStepMaterialRoleInput, LeadTimeHours: 24, Source: domain.IngredientSourceBuy, FormulaID: "F-005", FormulaName: "Control Bracket BOM", IngredientID: "ING-F005-MAT012"},
		{ProductID: "P-005", StepID: "STP-P005-2", ProductIDComp: prod("P-005"), Qty: 1, Unit: "pcs", Role: domain.ProcessStepMaterialRoleOutput, FormulaID: "F-005", FormulaName: "Control Bracket BOM", IngredientID: ""},
		// P-006
		{ProductID: "P-006", StepID: "STP-P006-1", MaterialID: mat("MAT-009"), Qty: 12.0, Unit: "kg", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceBuy, FormulaID: "F-006", FormulaName: "Pump Casing BOM", IngredientID: "ING-F006-MAT009"},
		{ProductID: "P-006", StepID: "STP-P006-1", MaterialID: mat("MAT-013"), Qty: 2, Unit: "pcs", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceBuy, FormulaID: "F-006", FormulaName: "Pump Casing BOM", IngredientID: "ING-F006-MAT013"},
		{ProductID: "P-006", StepID: "STP-P006-3", ProductIDComp: prod("P-003"), Qty: 1, Unit: "pcs", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceMake, ScrapRate: 0.01, FormulaID: "F-006", FormulaName: "Pump Casing BOM", IngredientID: "ING-F006-P003"},
		{ProductID: "P-006", StepID: "STP-P006-3", ProductIDComp: prod("P-009"), Qty: 1, Unit: "set", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceMake, ScrapRate: 0.02, FormulaID: "F-006", FormulaName: "Pump Casing BOM", IngredientID: "ING-F006-P009"},
		{ProductID: "P-006", StepID: "STP-P006-3", ProductIDComp: prod("P-006"), Qty: 1, Unit: "pcs", Role: domain.ProcessStepMaterialRoleOutput, FormulaID: "F-006", FormulaName: "Pump Casing BOM", IngredientID: ""},
		// P-007
		{ProductID: "P-007", StepID: "STP-P007-1", MaterialID: mat("MAT-010"), Qty: 8, Unit: "pcs", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceBuy, FormulaID: "F-007", FormulaName: "Seal Kit Mix", IngredientID: "ING-F007-MAT010"},
		{ProductID: "P-007", StepID: "STP-P007-1", MaterialID: mat("MAT-011"), Qty: 1, Unit: "set", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceBuy, FormulaID: "F-007", FormulaName: "Seal Kit Mix", IngredientID: "ING-F007-MAT011"},
		{ProductID: "P-007", StepID: "STP-P007-1", MaterialID: mat("MAT-014"), Qty: 0.5, Unit: "set", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceBuy, FormulaID: "F-007", FormulaName: "Seal Kit Mix", IngredientID: "ING-F007-MAT014"},
		{ProductID: "P-007", StepID: "STP-P007-2", ProductIDComp: prod("P-007"), Qty: 1, Unit: "set", Role: domain.ProcessStepMaterialRoleOutput, FormulaID: "F-007", FormulaName: "Seal Kit Mix", IngredientID: ""},
		// P-008
		{ProductID: "P-008", StepID: "STP-P008-1", MaterialID: mat("MAT-002"), Qty: 0.5, Unit: "kg", Role: domain.ProcessStepMaterialRoleInput, LeadTimeHours: 24, Source: domain.IngredientSourceBuy, FormulaID: "F-008", FormulaName: "Valve Spool BOM", IngredientID: "ING-F008-MAT002"},
		{ProductID: "P-008", StepID: "STP-P008-1", MaterialID: mat("MAT-004"), Qty: 0.8, Unit: "kg", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceBuy, FormulaID: "F-008", FormulaName: "Valve Spool BOM", IngredientID: "ING-F008-MAT004"},
		{ProductID: "P-008", StepID: "STP-P008-3", ProductIDComp: prod("P-008"), Qty: 1, Unit: "pcs", Role: domain.ProcessStepMaterialRoleOutput, FormulaID: "F-008", FormulaName: "Valve Spool BOM", IngredientID: ""},
		// P-009
		{ProductID: "P-009", StepID: "STP-P009-1", MaterialID: mat("MAT-011"), Qty: 2, Unit: "set", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceBuy, FormulaID: "F-009", FormulaName: "Gasket Set Mix", IngredientID: "ING-F009-MAT011"},
		{ProductID: "P-009", StepID: "STP-P009-1", MaterialID: mat("MAT-014"), Qty: 1, Unit: "set", Role: domain.ProcessStepMaterialRoleInput, Source: domain.IngredientSourceBuy, FormulaID: "F-009", FormulaName: "Gasket Set Mix", IngredientID: "ING-F009-MAT014"},
		{ProductID: "P-009", StepID: "STP-P009-2", ProductIDComp: prod("P-009"), Qty: 1, Unit: "set", Role: domain.ProcessStepMaterialRoleOutput, FormulaID: "F-009", FormulaName: "Gasket Set Mix", IngredientID: ""},
	}
}
