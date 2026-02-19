#!/bin/bash
# Security Scanning Script for Ansible SimpleWeb
# Runs automated security tools and generates reports

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
REPORT_DIR="$PROJECT_DIR/security-reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "======================================"
echo "Security Scan - Ansible SimpleWeb"
echo "======================================"
echo "Timestamp: $TIMESTAMP"
echo ""

# Create report directory
mkdir -p "$REPORT_DIR"

# Function to print section header
section() {
    echo ""
    echo -e "${YELLOW}=== $1 ===${NC}"
    echo ""
}

# Function to print success
success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

# Function to print warning
warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Function to print error
error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check for required tools
section "Checking Required Tools"

check_tool() {
    if command -v "$1" &> /dev/null; then
        success "$1 found"
        return 0
    else
        warning "$1 not found - installing..."
        pip install "$1" 2>/dev/null || {
            error "Failed to install $1"
            return 1
        }
        success "$1 installed"
    fi
}

check_tool bandit
check_tool pip-audit

# Run Bandit - Python Security Linter
section "Running Bandit Security Linter"

BANDIT_REPORT="$REPORT_DIR/bandit_report_$TIMESTAMP.txt"
BANDIT_JSON="$REPORT_DIR/bandit_report_$TIMESTAMP.json"

cd "$PROJECT_DIR"

echo "Scanning web/ and worker/ directories..."
bandit -r web/ worker/ -f txt -o "$BANDIT_REPORT" 2>&1 || true
bandit -r web/ worker/ -f json -o "$BANDIT_JSON" 2>&1 || true

# Count issues by severity
HIGH=$(grep -c "Severity: High" "$BANDIT_REPORT" 2>/dev/null || echo "0")
MEDIUM=$(grep -c "Severity: Medium" "$BANDIT_REPORT" 2>/dev/null || echo "0")
LOW=$(grep -c "Severity: Low" "$BANDIT_REPORT" 2>/dev/null || echo "0")

echo "Bandit Results:"
echo "  High severity:   $HIGH"
echo "  Medium severity: $MEDIUM"
echo "  Low severity:    $LOW"
echo ""
echo "Full report: $BANDIT_REPORT"

if [ "$HIGH" -gt 0 ]; then
    error "Found $HIGH high severity issues!"
elif [ "$MEDIUM" -gt 0 ]; then
    warning "Found $MEDIUM medium severity issues"
else
    success "No high or medium severity issues found"
fi

# Run pip-audit - Dependency Vulnerability Scanner
section "Running Dependency Vulnerability Scan"

AUDIT_REPORT="$REPORT_DIR/pip_audit_report_$TIMESTAMP.txt"

pip-audit > "$AUDIT_REPORT" 2>&1 || true

VULN_COUNT=$(grep -c "CVE-" "$AUDIT_REPORT" 2>/dev/null || echo "0")

echo "Dependency Vulnerabilities Found: $VULN_COUNT"
echo "Full report: $AUDIT_REPORT"

if [ "$VULN_COUNT" -gt 0 ]; then
    warning "Found $VULN_COUNT vulnerable dependencies"
    echo ""
    echo "Vulnerable packages:"
    grep -E "^[a-zA-Z]" "$AUDIT_REPORT" | head -20
else
    success "No known vulnerabilities in dependencies"
fi

# Check for common security issues in code
section "Checking for Common Security Issues"

echo "Checking for hardcoded secrets..."
SECRET_PATTERNS=(
    "password.*=.*['\"][^'\"]+['\"]"
    "secret.*=.*['\"][^'\"]+['\"]"
    "api_key.*=.*['\"][^'\"]+['\"]"
    "token.*=.*['\"][^'\"]+['\"]"
)

SECRET_FOUND=0
for pattern in "${SECRET_PATTERNS[@]}"; do
    COUNT=$(grep -rEi "$pattern" web/ worker/ --include="*.py" 2>/dev/null | grep -v "test" | grep -v "example" | grep -v "environ" | wc -l || echo "0")
    if [ "$COUNT" -gt 0 ]; then
        SECRET_FOUND=$((SECRET_FOUND + COUNT))
    fi
done

if [ "$SECRET_FOUND" -gt 0 ]; then
    warning "Found $SECRET_FOUND potential hardcoded secrets - manual review needed"
else
    success "No obvious hardcoded secrets detected"
fi

echo ""
echo "Checking for dangerous functions..."
DANGEROUS_FUNCTIONS=(
    "eval("
    "exec("
    "os.system("
    "pickle.load"
    "__import__"
)

DANGEROUS_FOUND=0
for func in "${DANGEROUS_FUNCTIONS[@]}"; do
    COUNT=$(grep -r "$func" web/ worker/ --include="*.py" 2>/dev/null | wc -l || echo "0")
    if [ "$COUNT" -gt 0 ]; then
        DANGEROUS_FOUND=$((DANGEROUS_FOUND + COUNT))
        warning "Found $COUNT uses of $func"
    fi
done

if [ "$DANGEROUS_FOUND" -eq 0 ]; then
    success "No dangerous function calls detected"
fi

# Generate summary report
section "Generating Summary Report"

SUMMARY_REPORT="$REPORT_DIR/security_summary_$TIMESTAMP.md"

cat > "$SUMMARY_REPORT" << EOF
# Security Scan Summary

**Date:** $(date)
**Project:** Ansible SimpleWeb

## Bandit Results (Python Security Linter)

| Severity | Count |
|----------|-------|
| High     | $HIGH |
| Medium   | $MEDIUM |
| Low      | $LOW |

## Dependency Vulnerabilities

Found **$VULN_COUNT** vulnerable packages.

## Manual Review Items

- Hardcoded secrets detected: $SECRET_FOUND
- Dangerous function calls: $DANGEROUS_FOUND

## Recommendations

1. Review and address all high severity Bandit findings
2. Update vulnerable dependencies to fixed versions
3. Manually review any flagged hardcoded secrets
4. Consider implementing Content Security Policy
5. Enable Strict-Transport-Security header in production

## Reports Generated

- Bandit text report: bandit_report_$TIMESTAMP.txt
- Bandit JSON report: bandit_report_$TIMESTAMP.json
- pip-audit report: pip_audit_report_$TIMESTAMP.txt
- This summary: security_summary_$TIMESTAMP.md
EOF

echo "Summary report: $SUMMARY_REPORT"

# Final summary
section "Scan Complete"

echo "Reports saved to: $REPORT_DIR/"
echo ""
echo "Quick Summary:"
echo "  - Bandit: $HIGH high, $MEDIUM medium, $LOW low severity issues"
echo "  - Dependencies: $VULN_COUNT vulnerabilities"
echo ""

if [ "$HIGH" -gt 0 ] || [ "$VULN_COUNT" -gt 5 ]; then
    error "Security issues require attention!"
    exit 1
else
    success "Security scan completed"
    exit 0
fi
