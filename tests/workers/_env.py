"""Optional native dependencies; tests that need them skip with a reason instead of failing."""
import contextlib
import io


def pymeshlab_ready():
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            import pymeshlab

            return hasattr(pymeshlab.MeshSet(), "meshing_decimation_quadric_edge_collapse")
    except Exception:
        return False


PYMESHLAB_REASON = "pymeshlab filters unavailable (pin pymeshlab==2023.12.post3; Linux also needs libOpenGL)"
