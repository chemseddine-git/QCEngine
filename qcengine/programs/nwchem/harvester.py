import json
import logging
import re
from decimal import Decimal
from typing import Tuple

import numpy as np
import qcelemental as qcel
from qcelemental.models import Molecule
from qcelemental.molparse import regex

from ..util import PreservingDict

logger = logging.getLogger(__name__)


def harvest_output(outtext: str) -> Tuple[PreservingDict, Molecule, list, str, str]:
    """Function to read an entire NWChem output file.

    Reads all of the different "line search" segments of a file and returns
    values from the last segment for which a geometry was written.

    Args:
        outtext (str): Output written to stdout
    Returns:
        - (PreservingDict) Variables extracted from the output file in the last complete step
        - (Molecule): Molecule from the last complete step
        - (list): Gradient from the last complete step
        - (str): Version string
        - (str): Error message, if any
    """

    # Loop over all steps
    # TODO (wardlt): Is it only necessary to read the last two steps?
    pass_psivar = []
    pass_coord = []
    pass_grad = []
    for outpass in re.split(r" Line search:", outtext, re.MULTILINE):
        psivar, nwcoord, nwgrad, version, error = harvest_outfile_pass(outpass)
        pass_psivar.append(psivar)
        pass_coord.append(nwcoord)
        pass_grad.append(nwgrad)

    # Determine which segment contained the last geometry
    retindx = -1 if pass_coord[-1] else -2

    return pass_psivar[retindx], pass_coord[retindx], pass_grad[retindx], version, error


def harvest_outfile_pass(outtext):
    """Function to read NWChem output file *outtext* and parse important
    quantum chemical information from it in

    """
    psivar = PreservingDict()
    psivar_coord = None
    psivar_grad = None
    version = ""
    error = ""  # TODO (wardlt): The error string is never used.

    NUMBER = r"(?x:" + regex.NUMBER + ")"

    # Process version
    mobj = re.search(
        r"^\s+" + r"Northwest Computational Chemistry Package (NWChem)" + r"\s+" + r"(?:<version>\d+.\d+)" + r"\s*$",
        outtext,
        re.MULTILINE,
    )
    if mobj:
        logger.debug("matched version")
        version = mobj.group("version")

    # Process SCF
    # 1)Fail to converge
    mobj = re.search(r"^\s+" + r"(?:Calculation failed to converge)" + r"\s*$", outtext, re.MULTILINE)
    if mobj:
        logger.debug("failed to converge")

    # 2)Calculation converged
    else:
        mobj = re.search(r"^\s+" + r"(?:Total SCF energy)" + r"\s+=\s*" + NUMBER + r"s*$", outtext, re.MULTILINE)
        if mobj:
            logger.debug("matched HF")
            psivar["HF TOTAL ENERGY"] = mobj.group(1)

        # Process Effective nuclear repulsion energy (a.u.)
        mobj = re.search(
            r"^\s+" + r"Effective nuclear repulsion energy \(a\.u\.\)" + r"\s+" + NUMBER + r"\s*$",
            outtext,
            re.MULTILINE,
        )
        if mobj:
            logger.debug("matched NRE")
            # logger.debug (mobj.group(1))
            psivar["NUCLEAR REPULSION ENERGY"] = mobj.group(1)

        # Process DFT dispersion energy (a.u.)
        mobj = re.search(r"^\s+" + r"(?:Dispersion correction)" + r"\s+=\s*" + NUMBER + r"\s*$", outtext, re.MULTILINE)
        if mobj:
            logger.debug("matched Dispersion")
            logger.debug(mobj.group(1))
            psivar["DFT DISPERSION ENERGY"] = mobj.group(1)

        # Process DFT (RDFT, RODFT,UDFT, SODFT [SODFT for nwchem versions before nwchem 6.8])

        mobj = re.search(r"^\s+" + r"(?:Total DFT energy)" + r"\s+=\s*" + NUMBER + r"\s*$", outtext, re.MULTILINE)
        if mobj:
            logger.debug("matched DFT")
            logger.debug(mobj.group(1))
            psivar["DFT TOTAL ENERGY"] = mobj.group(1)

        # SODFT [for nwchem 6.8+]
        mobj = re.search(
            # fmt: off
            r'^\s+' + r'Total SO-DFT energy' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Nuclear repulsion energy' + r'\s+' + NUMBER + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE,
        )
        if mobj:
            logger.debug("matched DFT")
            # print (mobj.group(1))
            psivar["DFT TOTAL ENERGY"] = mobj.group(1)
            psivar["NUCLEAR REPULSION ENERGY"] = mobj.group(2)

        # MCSCF
        mobj = re.findall(
            # fmt: off
            r'^\s+' + r'Total SCF energy' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'One-electron energy' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Two-electron energy' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Total MCSCF energy' + r'\s+' + NUMBER + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE | re.DOTALL,
        )

        # for mobj_list in mobj:

        if mobj:  # Need to change to accommodate find all instances
            logger.debug("matched mcscf")  # MCSCF energy calculation
            psivar["HF TOTAL ENERGY"] = mobj.group(1)
            psivar["ONE-ELECTRON ENERGY"] = mobj.group(2)
            psivar["TWO-ELECTRON ENERGY"] = mobj.group(3)
            psivar["MCSCF TOTAL ENERGY"] = mobj.group(4)
        # for mobj_list in mobj:
        #   for i in mobj_list:
        #       count += 0
        # logger.debug('matched mcscf iteration %i', count)
        # psivar['HF TOTAL ENERGY'] = mobj.group(1)
        # psivar['ONE-ELECTRON ENERGY'] = mobj.group(2)
        # psivar['TWO-ELECTRON ENERGY'] = mobj.group(3)
        # psivar['MCSCF TOTAL ENERGY'] = mobj.group(4)

        # Process MP2 (Restricted, Unrestricted(RO n/a))
        # 1)SCF-MP2
        mobj = re.search(
            # fmt: off
            r'^\s+' + r'SCF energy' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Correlation energy' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Singlet pairs' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Triplet pairs' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Total MP2 energy' + r'\s+' + NUMBER + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE,
        )  # MP2
        if mobj:
            logger.debug("matched scf-mp2")
            psivar["HF TOTAL ENERGY"] = mobj.group(1)
            psivar["MP2 CORRELATION ENERGY"] = mobj.group(2)
            psivar["MP2 TOTAL ENERGY"] = mobj.group(5)
        # SCS-MP2
        mobj = re.search(
            # fmt: off
            r'^\s+' + r'Same spin pairs' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Same spin scaling factor' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Opposite spin pairs' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Opposite spin scaling fact.' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'SCS-MP2 correlation energy' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Total SCS-MP2 energy' + r'\s+' + NUMBER + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE,
        )
        if mobj:
            logger.debug("matched scs-mp2")
            print("matched scs-mp2", mobj.groups())
            psivar["MP2 SAME-SPIN CORRELATION ENERGY"] = mobj.group(1)
            psivar["MP2 OPPOSITE-SPIN CORRELATION ENERGY"] = mobj.group(3)

            logger.debug(mobj.group(1))  # ess
            logger.debug(mobj.group(2))  # fss
            logger.debug(mobj.group(3))  # eos
            logger.debug(mobj.group(4))  # fos
            logger.debug(mobj.group(5))  # scs corl
            logger.debug(mobj.group(6))  # scs-mp2

        # 2) DFT-MP2
        mobj = re.search(
            # fmt: off
            r'^\s+' + r'DFT energy' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Unscaled MP2 energy' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Total DFT+MP2 energy' + r'\s+' + NUMBER + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE,
        )
        if mobj:
            logger.debug("matched dft-mp2")
            psivar["DFT TOTAL ENERGY"] = mobj.group(1)
            psivar["MP2 CORRELATION ENERGY"] = mobj.group(2)
            psivar["MP2 TOTAL ENERGY"] = mobj.group(3)

        # 3) MP2 with CCSD or CCSD(T) calculation (through CCSD(T) directive)
        mobj = re.search(
            # fmt: off
            r'^\s+' + r'MP2 Energy \(coupled cluster initial guess\)' + r'\s*' +
            r'^\s+' + r'------------------------------------------' + r'\s*' +
            r'^\s+' + r'Reference energy:' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'MP2 Corr\. energy:' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Total MP2 energy:' + r'\s+' + NUMBER + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE,
        )
        if mobj:
            logger.debug("matched coupled cluster-mp2")
            psivar["MP2 CORRELATION ENERGY"] = mobj.group(2)
            psivar["MP2 TOTAL ENERGY"] = mobj.group(3)

            mobj3 = re.search(r"Final RHF  results", outtext)
            if mobj3:
                psivar["MP2 DOUBLES ENERGY"] = mobj.group(2)

        # 4) Direct MP2

        # 5) RI-MP2

        # Process calculation through tce [dertype] command
        for cc_name in [r"MBPT\(2\)", r"MBPT\(3\)", r"MBPT\(4\)"]:
            mobj = re.search(
                # fmt: off
                r'^\s+' + cc_name + r'\s+' + r'correlation energy / hartree' + r'\s+=\s*' + NUMBER + r'\s*' +
                r'^\s+' + cc_name + r'\s+' + r'total energy / hartree' + r'\s+=\s*' + NUMBER + r'\s*$',
                # fmt: on
                outtext,
                re.MULTILINE,
            )

            if mobj:
                mbpt_plain = cc_name.replace("\\", "").replace("MBPT", "MP").replace("(", "").replace(")", "")
                logger.debug(f"matched tce mbpt {mbpt_plain}", mobj.groups())

                if mbpt_plain == "MP2":
                    mobj3 = re.search(r"Wavefunction type : Restricted open-shell Hartree-Fock", outtext, re.MULTILINE)
                    if mobj3:
                        psivar[f"{mbpt_plain} DOUBLES ENERGY"] = mobj.group(1)
                        psivar[f"CURRENT CORRELATION ENERGY"] = mobj.group(1)
                        psivar[f"CURRENT ENERGY"] = Decimal(mobj.group(1)) + psivar[f"HF TOTAL ENERGY"]
                    else:
                        psivar[f"{mbpt_plain} DOUBLES ENERGY"] = mobj.group(1)
                        psivar[f"{mbpt_plain} CORRELATION ENERGY"] = mobj.group(1)
                else:
                    psivar[f"{mbpt_plain} CORRECTION ENERGY"] = mobj.group(1)
                psivar[f"{mbpt_plain} TOTAL ENERGY"] = mobj.group(2)
            # TCE dipole- MBPT(n)
            mobj2 = re.search(
                # fmt: off
                r'^\s+' +  r'dipole moments / hartree & Debye' + r'\s*' +
                r'^\s+' + r'X' + r'\s+' + NUMBER + r'\s+' + NUMBER + r'\s*' +
                r'^\s+' + r'Y' + r'\s+' + NUMBER + r'\s+' + NUMBER + r'\s*' +
                r'^\s+' + r'Z' + r'\s+' + NUMBER + r'\s+' + NUMBER + r'\s*' +
                r'^\s+' + r'Total' + r'\s+' + NUMBER + r'\s+' + NUMBER + r'\s*$',
                # fmt: on
                outtext,
                re.MULTILINE,
            )

            if mobj2:
                mbpt_plain = cc_name.replace("\\", "").replace("MBPT", "MP").replace("(", "").replace(")", "")
                print(f"matched tce {mbpt_plain} dipole moment")
                # only pulling Debye
                psivar[f"{mbpt_plain} DIPOLE"] = np.array([mobj2.group(1), mobj2.group(3), mobj2.group(5)])

        # TCE with () or []
        for cc_name in [
            r"CCSD\(T\)",
            r"CCSD\[T\]",
            r"CCSD\(2\)_T",
            r"CCSD\(2\)",
            r"CCSDT\(2\)_Q",
            r"CR-CCSD\[T\]",
            r"CR-CCSD\(T\)",
            r"LR-CCSD\(T\)",
            r"LR-CCSD\(TQ\)-1",
            r"CREOMSD\(T\)",
        ]:
            mobj = re.search(
                # fmt: off
                r'^\s+' + cc_name + r'\s+' + r'correction energy / hartree' + r'\s+=\s*' + NUMBER + r'\s*' +
                r'^\s+' + cc_name + r'\s+' + r'correlation energy / hartree' + r'\s+=\s*' + NUMBER + r'\s*' +
                r'^\s+' + cc_name + r'\s+' + r'total energy / hartree' + r'\s+=\s*' + NUMBER + r'\s*$',
                # fmt: on
                outtext,
                re.MULTILINE,
            )
            if mobj:
                cc_plain = cc_name.replace("\\", "")
                cc_corr = cc_plain.replace("CCSD", "")
                logger.debug(f"matched tce cc {cc_plain}")

                psivar[f"{cc_corr} CORRECTION ENERGY"] = mobj.group(1)
                psivar[f"{cc_plain} CORRELATION ENERGY"] = mobj.group(2)
                psivar[f"{cc_plain} TOTAL ENERGY"] = mobj.group(3)
            # TCE dipole with () or []
            mobj2 = re.search(
                # fmt: off
                r'^\s+' + cc_name + r'dipole moments / hartree & Debye' + r'\s*' +
                r'^\s+' + r'X' + r'\s+' + NUMBER + r'\s+' + NUMBER + r'\s*' +
                r'^\s+' + r'Y' + r'\s+' + NUMBER + r'\s+' + NUMBER + r'\s*' +
                r'^\s+' + r'Z' + r'\s+' + NUMBER + r'\s+' + NUMBER + r'\s*' +
                r'^\s+' + r'Total' + r'\s+' + NUMBER + r'\s+' + NUMBER + r'\s*$',
                # fmt: on
                outtext,
                re.MULTILINE,
            )

            if mobj2:
                cc_plain = cc_name.replace("\\", "")
                cc_corr = cc_plain.replace("CCSD", "")
                print(f"matched tce {cc_plain} dipole moment")

                # only pulling Debye
                psivar[f"{cc_plain} DIPOLE"] = np.array([mobj2.group(1), mobj2.group(3), mobj2.group(5)])

        # Process other TCE cases
        for cc_name in [
            r"CISD",
            r"CISDT",
            r"CISDTQ",
            r"CCD",
            r"CC2",
            r"CCSD",
            r"CCSDT",
            r"CCSDTQ",
            r"LCCSD",
            r"LCCD",
            r"CCSDTA",
        ]:
            mobj = re.search(
                # fmt: off
                r'^\s+' + r'Iterations converged' + r'\s*' +
                r'^\s+' + cc_name + r'\s+' + r'correlation energy / hartree' + r'\s+=\s*' + NUMBER + r'\s*' +
                r'^\s+' + cc_name + r'\s+' + r'total energy / hartree' + r'\s+=\s*' + NUMBER + r'\s*$',
                # fmt: on
                outtext,
                re.MULTILINE,
            )

            if mobj:
                logger.debug(f"matched {cc_name}")
                mobj3 = re.search(r"Wavefunction type : Restricted open-shell Hartree-Fock", outtext, re.MULTILINE)
                print(f"matched {cc_name}", mobj.groups())
                if mobj3:
                    pass
                else:
                    psivar[f"{cc_name} DOUBLES ENERGY"] = mobj.group(1)
                psivar[f"{cc_name} CORRELATION ENERGY"] = mobj.group(1)
                psivar[f"{cc_name} TOTAL ENERGY"] = mobj.group(2)
            # TCE dipole
            mobj2 = re.search(
                # fmt: off
                r'^\s+' + r'dipole moments / hartree & Debye' + r'\s*' +
                r'^\s+' + r'X' + r'\s+' + NUMBER + r'\s+' + NUMBER + r'\s*' +
                r'^\s+' + r'Y' + r'\s+' + NUMBER + r'\s+' + NUMBER + r'\s*' +
                r'^\s+' + r'Z' + r'\s+' + NUMBER + r'\s+' + NUMBER + r'\s*' +
                r'^\s+' + r'Total' + r'\s+' + NUMBER + r'\s+' + NUMBER + r'\s*$',
                # fmt: on
                outtext,
                re.MULTILINE,
            )
            if mobj2:
                print(f"matched tce dipole moment")

                # only pulling Debye
                psivar[f"CURRENT DIPOLE"] = np.array([mobj2.group(1), mobj2.group(3), mobj2.group(5)])

        # Process CCSD/CCSD(T) using nwchem CCSD/CCSD(T) [dertype] command

        mobj = re.search(
            # fmt: off
            r'^\s+' + r'-----------' + r'\s*' +
            r'^\s+' + r'CCSD Energy' + r'\s*' +
            r'^\s+' + r'-----------' + r'\s*' +
            r'^\s+' + r'Reference energy:' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'CCSD corr\. energy:' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Total CCSD energy:' + r'\s+' + NUMBER + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE | re.DOTALL,
        )

        if mobj:
            logger.debug("matched ccsd")
            print("matched ccsd")
            psivar["CCSD CORRELATION ENERGY"] = mobj.group(2)
            psivar["CCSD TOTAL ENERGY"] = mobj.group(3)

        mobj = re.search(
            # fmt: off
            r'^\s+' + r'--------------' + r'\s*' +
            r'^\s+' + r'CCSD\(T\) Energy' + r'\s*' +
            r'^\s+' + r'--------------' + r'\s*' + r'(?:.*?)' +
            r'^\s+' + r'\(T\) corr\. energy:' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Total CCSD\(T\) energy:' + r'\s+' + NUMBER + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE | re.DOTALL,
        )

        if mobj:
            logger.debug("matched ccsd(t)")
            psivar["(T) CORRECTION ENERGY"] = mobj.group(1)
            psivar["CCSD(T) CORRELATION ENERGY"] = Decimal(mobj.group(2)) - psivar["HF TOTAL ENERGY"]
            psivar["CCSD(T) TOTAL ENERGY"] = mobj.group(2)

        mobj = re.search(
            # fmt: off
            r'^\s+' + r'Spin Component Scaled \(SCS\) CCSD' + r'\s*' +
            r'^\s+' + r'-*' + r'\s*' +
            r'^\s+' + r'Same spin contribution:' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Same spin scaling factor:' + r'\s+' + NUMBER + r'\s*'
            r'^\s+' + r'Opposite spin contribution:' + r'\s+' + NUMBER + r'\s*' +
            #r'^\s+' + r'Opposite spin scaling factor' + r'\s+' + NUMBER + r'\s*'
            r'^\s+' + r'Opposite spin scaling fact.:' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'SCS-CCSD correlation energy:' + r'\s+' + NUMBER + r'\s*' +
            r'^\s+' + r'Total SCS-CCSD energy:' + r'\s+' + NUMBER + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE | re.DOTALL,
        )
        # SCS-CCSD included
        if mobj:
            logger.debug("matched scs-ccsd")
            print("matched scs-ccsd", mobj.groups())
            psivar["CCSD SAME-SPIN CORRELATION ENERGY"] = mobj.group(1)
            psivar["CCSD OPPOSITE-SPIN CORRELATION ENERGY"] = mobj.group(3)
            # psivar['CCSD SAME-SPIN CORRELATION ENERGY'] = psivar['SCS-CCSD SAME-SPIN CORRELATION ENERGY'] = (
            #    Decimal(mobj.group(1)) * Decimal(mobj.group(2)))
            # psivar['CCSD OPPOSITE-SPIN CORRELATION ENERGY'] = psivar['SCS-CCSD OPPOSITE-SPIN CORRELATION ENERGY'] = (
            #    Decimal(mobj.group(4)) * Decimal(mobj.group(3)))
            # psivar['SCS-CCSD CORRELATION ENERGY'] = mobj.group(5)
            # psivar['SCS-CCSD TOTAL ENERGY'] = mobj.group(6)
            # psivar['CUSTOM SCS-CCSD CORRELATION ENERGY'] = 0.5 * (float(
            #    psivar['CCSD SAME-SPIN CORRELATION ENERGY']) + float(psivar['CCSD OPPOSITE-SPIN CORRELATION ENERGY']))
            # psivar['CUSTOM SCS-CCSD TOTAL ENERGY'] = float(mobj.group(6)) + float(
            #   psivar['CUSTOM SCS-CCSD CORRERLATION ENERGY'])

        # Process EOM-[cc_name] #nwchem_tce_dipole = false
        # Parsed information: each symmetry, root excitation energy in eV and total energy in hartree
        # psivar name might need to be fixed
        # each root excitation energy is extracted from the last iteration of right hand side
        mobj = re.findall(
            # fmt: off
            r'^\s+(?:Excited-state calculation \( )(.*)\s+(?:symmetry\))\s+(?:.*\n)*^\s+EOM-' + cc_name +
            # (..) captures symmetry
            r'right-hand side iterations\s+(?:.*\n)*(?:Excited state root)\s+' + NUMBER + #root
            r'\s*(?:Excitation energy / hartree)\s+.\s+' + NUMBER + #excitation energy hartree
            r'\s*(?:/ eV)\s+.\s+' + NUMBER + r'\s*$',
            # excitation energy eV
            # fmt: on
            outtext,
            re.MULTILINE | re.DOTALL,
        )
        # regex should be more dynamic in finding values, need to revisit
        # mobj.group(0) = symmetry value
        # mobj.group(1) = cc_name
        # mobj.group(2) = root number
        # mobj.group(3) = excitation energy (hartree)
        # mobj.group(4) = excitation energy (eV)

        if mobj:
            print(mobj)
            ext_energy = {}  # dic

            ext_energy_list = []
            print(f"matched eom-{cc_name}")
            for mobj_list in mobj:
                logger.debug("matched EOM-%s - %s symmetry" % (cc_name, mobj_list[0]))  # cc_name, symmetry
                logger.debug(mobj_list)
                count = 0
                for line in mobj_list[1].splitlines():
                    lline = line.split()
                    logger.debug(lline[1])  # in hartree
                    logger.debug(lline[2])  # in eV
                    count += 1

                    logger.debug("matched excitation energy #%d - %s symmetry" % (count, mobj_list[0]))

                    ext_energy_list.append(lline[1])  # Collect all excitation energies

                    sym = str(mobj_list[0])
                    ext_energy.setdefault(sym, [])
                    ext_energy[sym].append(lline[1])  # Dictionary: symmetries(key), energies(value)

            ext_energy_list.sort(key=float)

            for nroot in range(len(ext_energy_list)):
                for k, e_val in ext_energy.items():
                    if ext_energy_list[nroot] in e_val:
                        symm = k
                        # in hartree
                        psivar[
                            f"EOM-{cc_name} ROOT 0 -> ROOT {nroot + 1} EXCITATION ENERGY - {symm} SYMMETRY"
                        ] = ext_energy_list[nroot]
                        psivar[f"EOM-{cc_name} ROOT 0 -> ROOT {nroot + 1} TOTAL ENERGY - {symm} SYMMETRY"] = psivar[
                            f"{cc_name} TOTAL ENERGY"
                        ] + Decimal(ext_energy_list[nroot])
        gssym = ""
        gs = re.search(r"^\s+" + r"Ground-state symmetry is" + gssym + r"\s*$", outtext, re.MULTILINE)

        if gs:
            logger.debug("matched ground-state symmetry")
            psivar["GROUND-STATE SYMMETRY"] = gssym.group(1)

        # Process TDDFT
        #       1) Spin allowed
        mobj = re.findall(
            # fmt: off
            r'^\s+(?:Root)\s+(\d+)\s+(.*?)\s+' + NUMBER + r'\s(?:a\.u\.)\s+' + NUMBER + r'\s+(?:\w+)'
            #Root | symmetry | a.u. | eV
            + r'\s+(?:.\w+.\s+.\s+\d+.\d+)' #s2 value
            + r'\s+(?:.*\n)\s+Transition Moments\s+X\s+'+ NUMBER + r'\s+Y\s+'+ NUMBER+ r'\s+Z\s+'+ NUMBER #dipole
            + r'\s+Transition Moments\s+XX\s+'+ NUMBER + r'\s+XY\s+'+ NUMBER+ r'\s+XZ\s+'+ NUMBER #quadrople
            + r'\s+Transition Moments\s+YY\s+'+ NUMBER + r'\s+YZ\s+'+ NUMBER+ r'\s+ZZ\s+'+ NUMBER #quadrople
            + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE,
        )

        if mobj:
            logger.debug("matched TDDFT with transition moments")
            for mobj_list in mobj:
                print(mobj_list)
                # in eV
                psivar[f"TDDFT ROOT {mobj_list[0]} EXCITATION ENERGY - {mobj_list[1]} SYMMETRY"] = mobj_list[2]
                psivar[f"TDDFT ROOT {mobj_list[0]} EXCITED STATE ENERGY - {mobj_list[1]} SYMMETRY"] = psivar[
                    "DFT TOTAL ENERGY"
                ] + Decimal(mobj_list[2])
                #### temporary psivars ####
                # psivar['TDDFT ROOT %d %s %s EXCITATION ENERGY' %
                #       (mobj_list[0], mobj_list[1], mobj_list[2])] = mobj_list[3]  # in a.u.
                # psivar ['TDDFT ROOT %s %s %s EXCITED STATE ENERGY' %(mobj_list[0],mobj_list[1],mobj_list[2])] = \
                #    psivar ['DFT TOTAL ENERGY'] + Decimal(mobj_list[3])
                psivar["TDDFT ROOT %s DIPOLE X" % (mobj_list[0])] = mobj_list[5]
                psivar["TDDFT ROOT %s DIPOLE Y" % (mobj_list[0])] = mobj_list[6]
                psivar["TDDFT ROOT %s DIPOLE Z" % (mobj_list[0])] = mobj_list[7]
                psivar["TDDFT ROOT %s QUADRUPOLE XX" % (mobj_list[0])] = mobj_list[8]
                psivar["TDDFT ROOT %s QUADRUPOLE XY" % (mobj_list[0])] = mobj_list[9]
                psivar["TDDFT ROOT %s QUADRUPOLE XZ" % (mobj_list[0])] = mobj_list[10]
                psivar["TDDFT ROOT %s QUADRUPOLE YY" % (mobj_list[0])] = mobj_list[11]
                psivar["TDDFT ROOT %s QUADRUPOLE YZ" % (mobj_list[0])] = mobj_list[12]
                psivar["TDDFT ROOT %s QUADRUPOLE ZZ" % (mobj_list[0])] = mobj_list[13]

        #       2) Spin forbidden
        mobj = re.findall(
            # fmt: off
            r'^\s+(?:Root)\s+(\d+)\s+(.*?)\s+' + NUMBER + r'\s(?:a\.u\.)\s+' + NUMBER + r'\s+(?:\w+)'  # Root | symmetry | a.u. | eV
            + r'\s+(?:.\w+.\s+.\s+\d+.\d+)'  # s2 value
            + r'\s+Transition Moments\s+(?:Spin forbidden)' + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE,
        )
        # mobj.group(0) = Root
        # mobj.group(1) = symmetry
        # mobj.group(2) a.u.
        # mobj.group(3) e.V
        # mobj.group(4) Excitation energy
        # mobj.group(5) Excited state energy

        if mobj:
            logger.debug("matched TDDFT - spin forbidden")
            for mobj_list in mobj:
                #### temporary psivars ####
                # in eV
                psivar[f"TDDFT ROOT {mobj_list[0]} EXCITATION ENERGY - {mobj_list[2]} SYMMETRY"] = mobj_list[4]
                psivar[f"TDDFT ROOT {mobj_list[0]} EXCITED STATE ENERGY - {mobj_list[2]} SYMMETRY"] = psivar[
                    "DFT TOTAL ENERGY"
                ] + qcel.constants.converstion_factor("eV", "hartree") * Decimal(mobj_list[4])

                # psivar['TDDFT ROOT %s %s %s EXCITATION ENERGY' %
                #       (mobj_list[0], mobj_list[1], mobj_list[2])] = mobj_list[3]  # in a.u.
                # psivar['TDDFT ROOT %s %s %s EXCITED STATE ENERGY' %(mobj_list[0], mobj_list[1], mobj_list[2])] = \
                #    psivar['DFT TOTAL ENERGY'] + Decimal(mobj_list[3])
            if mobj:
                logger.debug("Non-variation initial energy")  # prints out energy, 5 counts

        # Process geometry
        # 1) CHARGE
        # Read charge from SCF module
        mobj = re.search(
            r"^\s+" + r"charge          =" + r"\s+" + NUMBER + r"\s*$", outtext, re.MULTILINE | re.IGNORECASE
        )

        if mobj:
            logger.debug("matched charge")
            out_charge = int(float(mobj.group(1)))

        # Read charge from General information (not scf module)
        mobj = re.search(
            r"^\s+" + r"Charge           :" + r"\s+" + r"(-?\d+)" + r"\s*$", outtext, re.MULTILINE | re.IGNORECASE
        )

        if mobj:
            logger.debug("matched charge")
            out_charge = int(float(mobj.group(1)))

        # 2) MULTIPLICITY
        # Read multiplicity from SCF module
        mobj = re.search(
            r"^\s+" + r"open shells     =" + r"\s+" + r"(\d+)" + r"\s*$", outtext, re.MULTILINE | re.IGNORECASE
        )

        if mobj:
            logger.debug("matched multiplicity")
            out_mult = int(mobj.group(1)) + 1

        # Read multiplicity from SCF module through alpha, beta electrons
        mobj = re.search(
            # fmt: off
            r'^\s+' + r'alpha electrons =' + r'\s+' + r'(\d+)' + r'\s*' +
            r'^\s+' + r'beta  electrons =' + r'\s+' + r'(\d+)' + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE | re.IGNORECASE,
        )

        if mobj:
            logger.debug("matched multiplicity via alpha and beta electrons")
            out_mult = int(mobj.group(1)) - int(mobj.group(2)) + 1  # nopen + 1
            psivar["N ALPHA ELECTRONS"] = mobj.group(1)
            psivar["N BETA ELECTRONS"] = mobj.group(2)

        # Read multiplicity from General information (not scf module)
        mobj = re.search(
            r"^\s+" + r"Spin multiplicity:" + r"\s+" + r"(\d+)" + r"\s*$", outtext, re.MULTILINE | re.IGNORECASE
        )

        if mobj:
            logger.debug("matched multiplicity")
            out_mult = int(mobj.group(1))

        # 3) Initial geometry
        mobj = re.search(
            # fmt: off
            r'^\s+' + r'Geometry' + r'.*' + r'\s*' +
            r'^\s+' + r'(?:-+)\s*' + r'\s+' + r'\n' +
            r'^\s' + r'Output coordinates in ' + r'(.*?)' + r'\s' + r'\(scale by' + r'.*' + r'\s' + r'to convert to a\.u\.\)' + r'\s+' + r'\n' +
            r'^\s+' + r'No\.\       Tag          Charge          X              Y              Z' + r'\s*' +
            r'^\s+' + r'---- ---------------- ---------- -------------- -------------- --------------' + r'\s*' +
            r'((?:\s+([1-9][0-9]*)+\s+([A-Z][a-z]*)+\s+\d+\.\d+\s+[-+]?\d+\.\d+\s+[-+]?\d+\.\d+\s+[-+]?\d+\.\d+\s*\n)+)' + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE | re.IGNORECASE,
        )

        if mobj:
            logger.debug("matched geom")

            # dinky molecule w/ charge and multiplicity
            if mobj.group(1) == "angstroms":
                molxyz = "%d \n%d %d tag\n" % (len(mobj.group(2).splitlines()), out_charge, out_mult)  # unit = angstrom
                for line in mobj.group(2).splitlines():
                    lline = line.split()
                    molxyz += "%s %16s %16s %16s\n" % (lline[-5], lline[-3], lline[-2], lline[-1])
                    # Jiyoung was collecting charge (-4)? see if this is ok for ghosts
                    # Tag    ,    X,        Y,        Z
                psivar_coord = Molecule(
                    validate=False,
                    **qcel.molparse.to_schema(
                        qcel.molparse.from_string(molxyz, dtype="xyz+", fix_com=True, fix_orientation=True)["qm"],
                        dtype=2,
                    ),
                )

            else:  # unit = a.u.
                molxyz = "%d au\n%d %d tag\n" % (len(mobj.group(2).splitlines()), out_charge, out_mult)
                for line in mobj.group(2).splitlines():
                    lline = line.split()
                    molxyz += "%s %16s %16s %16s\n" % (int(float(lline[-4])), lline[-3], lline[-2], lline[-1])
                    # Tag    ,    X,        Y,        Z
                psivar_coord = Molecule(
                    validate=False,
                    **qcel.molparse.to_schema(
                        qcel.molparse.from_string(molxyz, dtype="xyz+", fix_com=True, fix_orientation=True)["qm"],
                        dtype=2,
                    ),
                )

        # Process gradient
        mobj = re.search(
            # fmt: off
            r'^\s+' + r'.*' + r'ENERGY GRADIENTS' + r'\s*' + r'\s+' + r'\n' +
            r'^\s+' + r'atom               coordinates                        gradient' + r'\s*' +
            r'^\s+' + r'x          y          z           x          y          z' + r'\s*' +
            r'((?:\s+([1-9][0-9]*)+\s+([A-Z][a-x]*)+\s+[-+]?\d+\.\d+\s+[-+]?\d+\.\d+\s+[-+]?\d+\.\d+\s+[-+]?\d+\.\d+\s+[-+]?\d+\.\d+\s+[-+]?\d+\.\d+\s*\n)+)' + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE,
        )

        if mobj:
            logger.debug("matched molgrad")
            atoms = []
            psivar_grad = []
            for line in mobj.group(1).splitlines():
                lline = line.split()  # Num, Tag, coord x, coord y, coord z, grad x, grad y, grad z
                # print (lline)
                if lline == []:
                    pass
                else:
                    atoms.append(lline[1])  # Tag
                    psivar_grad.append([float(lline[-3]), float(lline[-2]), float(lline[-1])])

        # Process dipole (Properties)
        mobj = re.search(
            # fmt: off
            r'^\s+' + r'Dipole moment' + r'\s+' + NUMBER + r'\s+' + r'A\.U\.' + r'\s*' +
            r'^\s+' + r'DMX' + r'\s+' + NUMBER + r'.*' +
            r'^\s+' + r'DMY' + r'\s+' + NUMBER + r'.*' +
            r'^\s+' + r'DMZ' + r'\s+' + NUMBER + r'.*' +
            r'^\s+' + r'.*' +
            r'^\s+' + r'Total dipole' + r'\s+' + NUMBER + r'\s+' + r'A\.U\.' + r'\s*' +
            r'^\s+' + r'Dipole moment' + r'\s+' + NUMBER + r'\s' + r'Debye\(s\)' + r'\s*' +
            r'^\s+' + r'DMX' + r'\s+' + NUMBER + r'.*' +
            r'^\s+' + r'DMY' + r'\s+' + NUMBER + r'.*' +
            r'^\s+' + r'DMZ' + r'\s+' + NUMBER + r'.*' +
            r'^\s+' + r'.*' +
            r'^\s+' + r'Total dipole' + r'\s+' + NUMBER + r'\s' + r'DEBYE\(S\)' + r'\s*$',
            # fmt: on
            outtext,
            re.MULTILINE,
        )

        if mobj:
            logger.debug("matched total dipole")

            # UNIT = DEBYE(S)
            psivar[f"CURRENT DIPOLE"] = d2au * np.array([mobj.group(7), mobj.group(8), mobj.group(9)])
            # total?

            # Process error code
            mobj = re.search(
                # fmt: off
                r'^\s+' + r'current input line \:' + r'\s*' +
                r'^\s+' + r'([1-9][0-9]*)' + r'\:' + r'\s+' + r'(.*)' + r'\s*' +
                r'^\s+' r'------------------------------------------------------------------------' + r'\s*' +
                r'^\s+' r'------------------------------------------------------------------------' + r'\s*' +
                r'^\s+' + r'There is an error in the input file' + r'\s*$',
                # fmt: on
                outtext,
                re.MULTILINE,
            )
            if mobj:
                logger.debug("matched error")
            # print (mobj.group(1)) #error line number
            # print (mobj.group(2)) #error reason
            psivar["NWCHEM ERROR CODE"] = mobj.group(1)
            # TODO process errors into error var

    # Get the size of the basis sets, etc
    mobj = re.search(r"No. of atoms\s+:\s+(\d+)", outtext, re.MULTILINE)
    if mobj:
        psivar["N ATOMS"] = mobj.group(1)
    mobj = re.search(
        r"No. of electrons\s+:\s+(\d+)\s+Alpha electrons\s+:\s+(\d+)\s+Beta electrons\s+:\s+(\d+)",
        outtext,
        re.MULTILINE,
    )
    if mobj:
        psivar["N ALPHA ELECTRONS"] = mobj.group(2)
        psivar["N BETA ELECTRONS"] = mobj.group(3)
        if psivar["N ALPHA ELECTRONS"] == psivar["N BETA ELECTRONS"]:
            # get HOMO and LUMO energy
            mobj = re.search(
                r"Vector"
                + r"\s+"
                + r"%d" % (psivar["N ALPHA ELECTRONS"])
                + r"\s+"
                + r"Occ="
                + r".*"
                + r"\s+"
                + r"E="
                + r"([+-]?\s?\d+[.]\d+)"
                + r"[D]"
                + r"([+-]0\d)",
                outtext,
                re.MULTILINE,
            )
            if mobj:
                homo = float(mobj.group(1)) * (10 ** (int(mobj.group(2))))
                psivar["HOMO"] = np.array([round(homo, 10)])
            mobj = re.search(
                r"Vector"
                + r"\s+"
                + r"%d" % (psivar["N ALPHA ELECTRONS"] + 1)
                + r"\s+"
                + r"Occ="
                + r".*"
                + r"\s+"
                + r"E="
                + r"([+-]?\s?\d+[.]\d+)"
                + r"[D]"
                + r"([+-]0\d)",
                outtext,
                re.MULTILINE,
            )
            if mobj:
                lumo = float(mobj.group(1)) * (10 ** (int(mobj.group(2))))
                psivar["LUMO"] = np.array([round(lumo, 10)])

    mobj = re.search(r"AO basis - number of functions:\s+(\d+)\s+number of shells:\s+(\d+)", outtext, re.MULTILINE)
    if mobj:
        psivar["N MOLECULAR ORBITALS"] = mobj.group(2)
        psivar["N BASIS FUNCTIONS"] = mobj.group(1)

    # Search for Center of charge
    mobj = re.search(
        r"Center of charge \(in au\) is the expansion point"
        + r"\n"
        + r"\s+"
        + r"X\s+=\s+([+-]?\d+[.]\d+)"
        + r"\s+"
        + r"Y\s+=\s+([+-]?\d+[.]\d+)"
        + r"\s+"
        + r"Z\s+=\s+([+-]?\d+[.]\d+)",
        outtext,
        re.MULTILINE,
    )
    if mobj:
        psivar["CENTER OF CHARGE"] = np.array([mobj.group(1), mobj.group(2), mobj.group(3)])

    mobj = re.search(
        r"Dipole moment"
        + r".*?"
        + r"A\.U\."
        + r"\s+"
        + r"DMX\s+([+-]?\d+[.]\d+)\s+"
        + r"DMXEFC\s+[+-]?\d+[.]\d+\s+"
        + r"DMY\s+([+-]?\d+[.]\d+)\s+"
        + r"DMYEFC\s+[+-]?\d+[.]\d+\s+"
        + r"DMZ\s+([+-]?\d+[.]\d+)\s+"
        + r"DMZEFC\s+[+-]?\d+[.]\d+\s+"
        + r"\-EFC\-"
        + r".*?"
        + r"A\.U\.\s+"
        + r"Total dipole\s+([+-]?\d+[.]\d+\s+)",
        outtext,
        re.MULTILINE,
    )
    # + r"DMY\s+" + r"([+-]?\d+[.]\d+)", outtext, re.MULTILINE)
    if mobj:
        psivar["DIPOLE MOMENT"] = np.array([mobj.group(1), mobj.group(2), mobj.group(3)])
        psivar["TOTAL DIPOLE MOMENT"] = mobj.group(4)
    # Process CURRENT energies (TODO: needs better way)
    if "HF TOTAL ENERGY" in psivar:
        psivar["SCF TOTAL ENERGY"] = psivar["HF TOTAL ENERGY"]
        psivar["CURRENT REFERENCE ENERGY"] = psivar["HF TOTAL ENERGY"]
        psivar["CURRENT ENERGY"] = psivar["HF TOTAL ENERGY"]

    if "MP2 TOTAL ENERGY" in psivar and "MP2 CORRELATION ENERGY" in psivar:
        psivar["CURRENT CORRELATION ENERGY"] = psivar["MP2 CORRELATION ENERGY"]
        psivar["CURRENT ENERGY"] = psivar["MP2 TOTAL ENERGY"]

    if "MP3 TOTAL ENERGY" in psivar and "MP3 CORRELATION ENERGY" in psivar:
        psivar["CURRENT CORRELATION ENERGY"] = psivar["MP3 CORRELATION ENERGY"]
        psivar["CURRENT ENERGY"] = psivar["MP3 TOTAL ENERGY"]
    if "MP4 TOTAL ENERGY" in psivar and "MP4 CORRELATION ENERGY" in psivar:
        psivar["CURRENT CORRELATION ENERGY"] = psivar["MP4 CORRELATION ENERGY"]
        psivar["CURRENT ENERGY"] = psivar["MP4 TOTAL ENERGY"]

    if "DFT TOTAL ENERGY" in psivar:
        psivar["CURRENT REFERENCE ENERGY"] = psivar["DFT TOTAL ENERGY"]
        psivar["CURRENT ENERGY"] = psivar["DFT TOTAL ENERGY"]

    # Process TCE CURRENT energies
    # Need to be fixed
    # HOW TO KNOW options['NWCHEM']['NWCHEM_TCE']['value']?
    # TODO: CURRENT ENERGY = TCE ENERGY
    if "%s TOTAL ENERGY" % (cc_name) in psivar and ("%s CORRELATION ENERGY" % (cc_name) in psivar):
        psivar["CURRENT CORRELATION ENERGY"] = psivar["%s CORRELATION ENERGY" % (cc_name)]
        psivar["CURRENT ENERGY"] = psivar["%s TOTAL ENERGY" % (cc_name)]

    if "CCSD TOTAL ENERGY" in psivar and "CCSD CORRELATION ENERGY" in psivar:
        psivar["CURRENT CORRELATION ENERGY"] = psivar["CCSD CORRELATION ENERGY"]
        psivar["CURRENT ENERGY"] = psivar["CCSD TOTAL ENERGY"]

    if "CCSD(T) TOTAL ENERGY" in psivar and "CCSD(T) CORRELATION ENERGY" in psivar:
        psivar["CURRENT CORRELATION ENERGY"] = psivar["CCSD(T) CORRELATION ENERGY"]
        psivar["CURRENT ENERGY"] = psivar["CCSD(T) TOTAL ENERGY"]

    if ("EOM-%s TOTAL ENERGY" % (cc_name) in psivar) and ("%s EXCITATION ENERGY" % (cc_name) in psivar):
        psivar["CURRENT ENERGY"] = psivar["EOM-%s TOTAL ENERGY" % (cc_name)]
        psivar["CURRENT EXCITATION ENERGY"] = psivar["%s EXCITATION ENERGY" % (cc_name)]

    return psivar, psivar_coord, psivar_grad, version, error


def harvest_hessian(hess: str) -> np.ndarray:
    """Parses the contents of the NWChem hess file into a hessian array.

    Args:
        hess (str): Contents of the hess file
    Returns:
        (np.ndarray) Hessian matrix as a 2D array
    """

    # Change the "D[+-]" notation of Fortran output to "E[+-]" used by Python
    hess_conv = hess.replace("D", "E")

    # Parse all of the float values
    hess_tri = [float(x) for x in hess_conv.strip().splitlines()]

    # The value in the Hessian matrix is the lower triangle printed row-wise (e.g., 0,0 -> 1,0 -> 1,1 -> ...)
    n = int(np.sqrt(8 * len(hess_tri) + 1) - 1) // 2  # Size of the 2D matrix

    # Add the lower diagonal
    hess_arr = np.zeros((n, n))
    hess_arr[np.tril_indices(n)] = hess_tri

    # Transpose and then set the lower diagonal again
    hess_arr = np.transpose(hess_arr)  # Numpy implementations might only change the ordering to column-major
    hess_arr[np.tril_indices(n)] = hess_tri

    return hess_arr.T  # So that the array is listed in C-order, needed by some alignment routines


def harvest(in_mol: Molecule, nwout: str, **outfiles) -> Tuple[PreservingDict, None, list, Molecule, str, str]:
    """Parses all the pieces of output from NWChem: the stdout in
    *nwout* Scratch files are not yet considered at this moment.

    Args:
        in_mol (Molecule): Input molecule
        nwout (str): NWChem output molecule
        outfiles (dict): Dictionary of outfile files and their contents
    Returns:
        - (PreservingDict) Variables extracted from the output file in the last complete step
        - (None): Hessian from the last complete step (Not yet implemented)
        - (list): Gradient from the last complete step
        - (Molecule): Molecule from the last complete step
        - (str): Version string
        - (str): Error message, if any
    """

    # Parse the NWChem output
    out_psivar, out_mol, out_grad, version, error = harvest_output(nwout)

    # If available, read higher-accuracy gradients
    #  These were output using a Python Task in NWChem to read them out of the database
    if outfiles.get("nwchem.grad") is not None:
        logger.debug("Reading higher-accuracy gradients")
        out_grad = json.loads(outfiles.get("nwchem.grad"))

    # If available, read the hessian
    out_hess = None
    if outfiles.get("nwchem.hess") is not None:
        out_hess = harvest_hessian(outfiles.get("nwchem.hess"))

    # Make sure the input and output molecules are the same
    if out_mol:
        if in_mol:
            if abs(out_mol.nuclear_repulsion_energy() - in_mol.nuclear_repulsion_energy()) > 1.0e-3:
                raise ValueError(
                    """NWChem outfile (NRE: %f) inconsistent with Psi4 input (NRE: %f)."""
                    % (out_mol.nuclear_repulsion_energy(), in_mol.nuclear_repulsion_energy())
                )
    else:
        raise ValueError("""No coordinate information extracted from NWChem output.""")

    # If present, align the gradients and hessian with the original molecular coordinates
    #  NWChem rotates the coordinates of the input molecule. `out_mol` contains the coordinates for the
    #  rotated molecule, which we can use to determine how to rotate the gradients/hessian
    amol, data = out_mol.align(in_mol, atoms_map=False, mols_align=True, verbose=0)

    mill = data["mill"]  # Retrieve tool with alignment routines

    if out_grad is not None:
        out_grad = mill.align_gradient(np.array(out_grad).reshape(-1, 3))
    if out_hess is not None:
        out_hess = mill.align_hessian(np.array(out_hess))

    return out_psivar, out_hess, out_grad, out_mol, version, error
