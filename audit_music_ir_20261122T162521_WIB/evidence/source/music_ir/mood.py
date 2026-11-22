"""Explicit mood scope and inspectable audio proxies; never song-specific rules."""

DEFAULT_POLICY = {"default_basis": "both", "sad_max_valence": .5, "sad_max_energy": .65,
                  "happy_min_valence": .5}


def apply_mood(intent, plan, config, requested=None):
    if requested not in {None, "lyrics", "audio", "both"}:
        raise ValueError("mood_basis harus lyrics, audio, atau both.")
    if plan is None or plan.mood is None:
        if requested is not None:
            raise ValueError("Pilihan mood hanya tersedia untuk query suasana yang dikenali.")
        return None
    policy = {**DEFAULT_POLICY, **config.get("mood", {})}
    basis = requested or policy["default_basis"]
    if basis not in {"lyrics", "audio", "both"}:
        raise ValueError("mood.default_basis harus lyrics, audio, atau both.")
    constraints = []
    if basis in {"audio", "both"}:
        if plan.mood == "sad":
            constraints = [("valence", "<=", policy["sad_max_valence"]),
                           ("energy", "<=", policy["sad_max_energy"])]
        else:
            constraints = [("valence", ">=", policy["happy_min_valence"])]
        for constraint in constraints:
            if constraint not in intent.constraints:
                intent.constraints.append(constraint)
    if basis == "audio":
        intent.text = ""
        high = plan.mood == "happy"
        intent.preferences.setdefault("valence", high)
        intent.preferences.setdefault("energy", high)
    return {"label": plan.mood, "basis": basis,
            "audio_constraints": constraints,
            "note": "Nuansa musik diperkirakan dari valence/energy pada dataset; ini bukan pengenal emosi yang pasti dan bukan hasil mendengarkan audio."}
