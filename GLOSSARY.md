# Infrastructure recommendations

InfraMind helps a developer turn workload requirements and repository evidence into an AWS sizing decision and deployment handoff.

## Language

**Recommendation**:
A proposed compute, database, cache and traffic distribution design for a workload. It is a sizing decision to review and benchmark, not a guarantee of capacity.

**Consistency check**:
A check for contradictions between a recommendation and its technical needs. An unavailable check is unverified; agreement does not establish production readiness.
_Avoid_: Certification, production approval

**Infrastructure scaffold**:
An initial resource definition that requires review and application-specific configuration before use. It does not include a running application.
_Avoid_: Complete deployment

**Deployment handoff**:
The generated resources, unresolved decisions and concrete next steps needed to take a recommendation toward an application deployment.
_Avoid_: Readiness score

**Instance subtotal**:
An estimate for the selected compute, database and cache instances. It excludes other infrastructure and operational charges.
_Avoid_: Total AWS bill
