"""Import externally authored comparisons; no network or semantic invention."""

from ..adaptive.state import fingerprint
from ..levels.protocol import Usage
from .runner import TeacherReply


class UnavailableTeacher:
    paid = False
    name = model = "NO_TEACHER_CONFIGURED"
    version = "1"

    def estimate(self, request):
        raise ValueError("Provide an external comparison bundle; no teacher configured")


class UncertainExtractor:
    paid = False
    name = "conservative-local"
    version = "1"

    def extract(self, request, content):
        return {"KNOWN_BY_BOTH": [], "MISSING_IN_COPYCAT": [], "WRONG_IN_COPYCAT": [],
                "EXTRA_IN_COPYCAT": [], "UNCERTAIN_DELTA": ["Semantic comparison requires a specialist."],
                "learning_value": "LOW", "reason": "INSUFFICIENT_EVIDENCE"}


class ImportedComparison:
    """Teacher and extractor interface backed by exact externally supplied cases."""
    paid = False

    def __init__(self, bundle):
        self.name = bundle["teacher_identity"]
        self.model = bundle["teacher_model"]
        self.version = bundle["teacher_version"] + ":" + fingerprint(bundle)
        self.cases = bundle["cases"]

    def case(self, request):
        matches = [c for c in self.cases if all(c[k] == request[k] for k in ("probe_id", "prompt", "copycat_output", "criterion"))]
        if len(matches) != 1:
            raise ValueError("Exactly one matching external case is required")
        return matches[0]

    def estimate(self, request):
        self.case(request)
        return Usage(0, 0, api_calls=0, cost_usd="0")

    def generate(self, request):
        return TeacherReply(self.case(request)["teacher_output"], Usage(0, 0, api_calls=0, cost_usd="0"))

    def extract(self, request, content):
        return self.case(request)["delta"]
