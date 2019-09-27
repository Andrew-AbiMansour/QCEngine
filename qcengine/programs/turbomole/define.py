from subprocess import Popen, PIPE, TimeoutExpired
from typing import Any, Dict, Optional

from .methods import METHODS, KEYWORDS


def execute_define(stdin: str, cwd: Optional["Path"] = None) -> str:
    # TODO: replace this with a call to the default execute provided by QCEngine
    # if possible. May be difficult though, as we have to pipe in stdin and
    # be careful with the encoding.

    # We cant use univeral_newlines=True or text=True in Popen as some of the
    # data that define returns isn't proper UTF-8, so the decoding will crash.
    # We will decode it later on manually.
    proc = Popen("define",
                 stdin=PIPE, stdout=PIPE, stderr=PIPE, cwd=cwd,
                 # stdin=PIPE, stderr=PIPE, cwd=cwd,
    )
    # TODO: Add timeout? Unless the disk hangs this should never take long...
    # TODO: If used with timeout an exception will be thrown. Then how do we
    # propagate the stdout produced until then to the user so he can see what
    # is going on?
    # TODO: How to get the stdout when the process hangs? Maybe write it to a file?
    stdout, _ = proc.communicate(str.encode(stdin))
    proc.terminate()
    try:
        stdout = stdout.decode("utf-8")
    except UnicodeDecodeError:
        # Some of the basis files (cbas, I'm looking at you ...) are saved
        # in ISO-8859-15 but most of them are in UTF-8. Decoding will
        # crash in the former cases so here we try the correct decoding.
        stdout = stdout.decode("latin-1")

    # try:
        # stdout, _ = proc.communicate(str.encode(stdin), timeout=5)
        # proc.terminate()
    # except TimeoutExpired as err:
        # print(err)
        # import pdb; pdb.set_trace()

    return stdout


def prepare_stdin(method: str, basis: str, keywords: Dict[str, Any],
                  charge: int, mult: int, geoopt: Optional[str] = "")  -> str:
    """Prepares a str that can be sent to define to produce the desired
    input for Turbomole."""

    # Load data from keywords
    unrestricted = keywords.get("unrestricted", False)
    grid = keywords.get("grid", "m3")

    def occ_num_mo_data(charge: int, mult: int,
                        unrestricted: Optional[bool] = False) -> str:
        """Handles the 'Occupation Number & Molecular Orbital' section
        of define. Sets appropriate charge and multiplicity in the
        system and decided between restricted and unrestricted calculation.

        RHF and UHF are supported. ROHF could be implemented later on
        by using the 's' command to list the available MOs and then
        close the appropriate number of MOs to doubly occupied MOs
        by 'c' by comparing the number of total MOs and the desired
        multiplicity."""

        # Do unrestricted calculation if explicitly requested or mandatory
        unrestricted = unrestricted or (mult != 1)
        unpaired = mult - 1
        charge = int(charge)

        occ_num_mo_data_stdin = f"""eht
        y
        {charge}
        y
        """
        if unrestricted:
            # Somehow Turbomole/define asks us if we want to write
            # natural orbitals... we don't want to.
            occ_num_mo_data_stdin = f"""eht
            y
            {charge}
            n
            u {unpaired}
            *
            n
            """
        return occ_num_mo_data_stdin

    def set_method(method, grid):
        if method == "hf":
            method_stdin = ""
        elif method in METHODS["ricc2"]:
            # Setting geoopt in $ricc2 will make the ricc2 module to produce
            # a gradient.
            # Drop the 'ri'-prefix of the method string.
            geoopt_stdin = f"geoopt {method[2:]} ({geoopt})" if geoopt else ""
            method_stdin = f"""cc
                               freeze
                               *
                               cbas
                               *
                               ricc2
                               {method}
                               list models

                               {geoopt_stdin}
                               list geoopt

                               *
                               *
                            """
        # Fallback: assume method corresponds to a DFT functional
        #
        # TODO: handle xcfuncs that aren't defined in define, e.g.
        # new functionals introduced in 7.4 from libxc. ...
        # Maybe the best idea would be to not set the functional here
        # but just turn on DFT and add it to the control file later on.
        else:
            method_stdin = f"""dft
                               on
                               func
                               {method}
                               grid
                               {grid}

                            """
        return method_stdin

    # Resolution of identity
    def set_ri(keywords):
        # TODO: senex/RIJCOSX?
        ri_kws = {ri_kw: keywords.get(ri_kw, False)
                  for ri_kw in KEYWORDS["ri"]}
        ri_stdins = {
            "rijk": "rijk\non\n\n",
            "ri": "ri\non\n\n",
            "marij": "marij\n\n",
        }
        ri_stdin = "\n".join([ri_stdins[ri_kw] for ri_kw, use in ri_kws.items()
                              if use
        ])
        return ri_stdin

        # ri_stdin = ""
        # # Use either RIJK or RIJ if requested.
        # if ri_kws["rijk"]:
            # ri_stdin = """rijk
                          # on

                       # """
        # elif ri_kws["rij"]:
            # ri_stdin = """rij
                         # on

                      # """
        # # MARIJ can be used additionally.
        # if ri_kws["marij"]:
            # ri_stdin += """marij

                        # """
        # return ri_stdin

    # Dispersion correction
    def set_dsp(keywords):
        # TODO: set_ri and set_dsp are basically the same funtion. Maybe
        # we could abstract this somehow?
        dsp_kws = {dsp_kw: keywords.get(dsp_kw, False)
                   for dsp_kw in KEYWORDS["dsp"]}
        dsp_stdins = {
            "d3": "dsp\non\n\n",
            "d3bj": "dsp\nbj\n\n",
        }
        dsp_stdin = "\n".join([dsp_stdins[dsp_kw]
                               for dsp_kw, use in dsp_kws.items() if use
        ])
        return dsp_stdin

    kwargs = {
        "init_guess": occ_num_mo_data(charge, mult, unrestricted),
        "set_method": set_method(method, grid),
        "ri": set_ri(keywords),
        "dsp": set_dsp(keywords),
        "title": "QCEngine Turbomole",
        "scf_conv": 8,
        "scf_iters": 150,
        "basis": basis,
    }

    stdin = """
    {title}
    a coord
    *
    no
    b
    all {basis}
    *
    {init_guess}
    {set_method}
    {ri}
    {dsp}
    scf
    conv
    {scf_conv}
    iter
    {scf_iters}

    *
    """.format(**kwargs)

    return stdin
