"""
30-Topic Prompt Evaluation Runner.

Runs PromptEvaluator over exactly 30 diverse test inputs (10 Physics, 10 Biology,
10 Chemistry — Class 11 and 12 mix) using MockLLMClient.
Evaluates versions v1, v2, v3 and saves:
  - outputs/eval_run/benchmark_<timestamp>.csv
  - outputs/eval_run/benchmark_<timestamp>.md
  - outputs/eval_run/benchmark_<timestamp>.json

Usage:
    python run_30_topic_eval.py
"""

from __future__ import annotations
import asyncio
import json
import os
import datetime
from prompt_manager import PromptManager
from script_generator import ScriptGenerator, MockLLMClient
from prompt_eval import PromptEvaluator, PromptVersionComparator

# ============================================================================
# 30 Diverse Test Topics
# 10 Physics + 10 Biology + 10 Chemistry (Classes 11 & 12 mix)
# ============================================================================
TEST_INPUTS = [
    # ─── Physics (10 topics) ────────────────────────────────────────────────
    {
        "subject": "Physics", "class_num": 11,
        "chapter": "Laws of Motion", "topic": "Newton's First Law & Inertia",
        "retrieved_context": (
            "Newton's First Law states that every object will remain at rest or in uniform motion "
            "in a straight line unless compelled to change its state by an external force. "
            "The tendency to resist changes in a state of motion is called inertia. "
            "Mass is the quantitative measure of inertia."
        ),
    },
    {
        "subject": "Physics", "class_num": 11,
        "chapter": "Laws of Motion", "topic": "Newton's Second Law & F=ma",
        "retrieved_context": (
            "Newton's Second Law states that the rate of change of linear momentum of a body is "
            "directly proportional to the applied external force and takes place in the direction "
            "of the force. F = ma, where F is force in Newtons, m is mass in kilograms, "
            "and a is acceleration in m/s^2."
        ),
    },
    {
        "subject": "Physics", "class_num": 11,
        "chapter": "Laws of Motion", "topic": "Newton's Third Law & Action-Reaction Pairs",
        "retrieved_context": (
            "Newton's Third Law states that to every action there is an equal and opposite reaction. "
            "Forces always occur in pairs. If body A exerts a force F on body B, then body B "
            "exerts an equal and opposite force -F on body A. These forces act on different bodies "
            "and never cancel each other."
        ),
    },
    {
        "subject": "Physics", "class_num": 11,
        "chapter": "Work, Energy and Power", "topic": "Work-Energy Theorem",
        "retrieved_context": (
            "The work-energy theorem states that the net work done on a body equals the change in "
            "its kinetic energy. W_net = delta_KE. Work is defined as the scalar product of force "
            "and displacement: W = F times d times cos(theta), where theta is the angle between "
            "force and displacement vectors."
        ),
    },
    {
        "subject": "Physics", "class_num": 11,
        "chapter": "Gravitation", "topic": "Universal Law of Gravitation",
        "retrieved_context": (
            "Newton's Universal Law of Gravitation states that every body in the universe attracts "
            "every other body with a force proportional to the product of their masses and inversely "
            "proportional to the square of the distance between them. F = G m1 m2 / r^2, where G is "
            "the universal gravitational constant equal to 6.67 x 10^-11 N m^2 per kg^2."
        ),
    },
    {
        "subject": "Physics", "class_num": 12,
        "chapter": "Electrostatics", "topic": "Coulomb's Law",
        "retrieved_context": (
            "Coulomb's Law states that the electrostatic force between two point charges is directly "
            "proportional to the product of the magnitudes of the charges and inversely proportional "
            "to the square of the distance between them. F = k q1 q2 / r^2, where k = 9 x 10^9 N m^2 C^-2 "
            "is Coulomb's constant in free space."
        ),
    },
    {
        "subject": "Physics", "class_num": 12,
        "chapter": "Current Electricity", "topic": "Ohm's Law & Resistance",
        "retrieved_context": (
            "Ohm's Law states that the current through a conductor between two points is directly "
            "proportional to the voltage across the two points. V = IR, where V is voltage in Volts, "
            "I is current in Amperes, and R is resistance in Ohms. Resistance depends on resistivity, "
            "length, and cross-sectional area of the conductor."
        ),
    },
    {
        "subject": "Physics", "class_num": 12,
        "chapter": "Electromagnetic Induction", "topic": "Faraday's Law & Lenz's Law",
        "retrieved_context": (
            "Faraday's First Law states that whenever the magnetic flux linked with a circuit changes, "
            "an emf is induced in it. Faraday's Second Law states that the induced emf is directly "
            "proportional to the rate of change of magnetic flux. Lenz's Law states that the induced "
            "current always opposes the change in magnetic flux that caused it."
        ),
    },
    {
        "subject": "Physics", "class_num": 12,
        "chapter": "Ray Optics", "topic": "Refraction & Snell's Law",
        "retrieved_context": (
            "Refraction is the bending of light as it passes from one medium to another due to change "
            "in speed. Snell's Law states that n1 sin(theta1) = n2 sin(theta2), where n1 and n2 are "
            "refractive indices and theta1 and theta2 are angles of incidence and refraction. "
            "The refractive index n = c divided by v, where c is speed of light in vacuum."
        ),
    },
    {
        "subject": "Physics", "class_num": 12,
        "chapter": "Dual Nature of Radiation", "topic": "Photoelectric Effect",
        "retrieved_context": (
            "The photoelectric effect is the emission of electrons from a metal surface when light of "
            "sufficient frequency falls on it. Einstein explained it using photon concept: E = hv, "
            "where h is Planck's constant and v is frequency. The maximum kinetic "
            "energy of emitted electrons is KE_max = hv minus work function of the metal."
        ),
    },

    # ─── Biology (10 topics) ────────────────────────────────────────────────
    {
        "subject": "Biology", "class_num": 11,
        "chapter": "Cell: The Unit of Life", "topic": "Cell Theory & Prokaryotic vs Eukaryotic Cells",
        "retrieved_context": (
            "Cell theory states that all living organisms are composed of cells, the cell is the basic "
            "unit of life, and all cells arise from pre-existing cells. Prokaryotic cells lack a "
            "membrane-bound nucleus and membrane-bound organelles. Eukaryotic cells have a true "
            "nucleus enclosed by a nuclear membrane and contain membrane-bound organelles."
        ),
    },
    {
        "subject": "Biology", "class_num": 11,
        "chapter": "Biomolecules", "topic": "Structure of DNA & Watson-Crick Model",
        "retrieved_context": (
            "DNA is a double-helical molecule composed of two antiparallel polynucleotide strands. "
            "Each nucleotide consists of a deoxyribose sugar, a phosphate group, and a nitrogenous base. "
            "Adenine pairs with Thymine via 2 hydrogen bonds and Guanine pairs with Cytosine via 3 hydrogen bonds. "
            "The two strands are held together by hydrogen bonds and coil around a common axis."
        ),
    },
    {
        "subject": "Biology", "class_num": 11,
        "chapter": "Photosynthesis", "topic": "Light Reactions & Calvin Cycle",
        "retrieved_context": (
            "Photosynthesis occurs in chloroplasts and involves two stages. The light reactions occur in "
            "the thylakoid membranes and produce ATP and NADPH. The Calvin cycle occurs in the stroma "
            "and uses ATP and NADPH to fix CO2 into glucose via RuBisCO enzyme. The overall equation is "
            "6CO2 + 6H2O + light energy produces C6H12O6 + 6O2."
        ),
    },
    {
        "subject": "Biology", "class_num": 11,
        "chapter": "Respiration in Plants", "topic": "Glycolysis & Krebs Cycle",
        "retrieved_context": (
            "Glycolysis occurs in the cytoplasm and breaks down one molecule of glucose (6C) into two "
            "molecules of pyruvate (3C), producing 2 ATP and 2 NADH. The Krebs Cycle occurs in the "
            "mitochondrial matrix. Each acetyl-CoA entering the cycle yields 3 NADH, 1 FADH2, and "
            "1 GTP per turn. Oxidative phosphorylation occurs in the inner mitochondrial membrane."
        ),
    },
    {
        "subject": "Biology", "class_num": 11,
        "chapter": "Plant Growth and Development", "topic": "Auxins and Plant Hormones",
        "retrieved_context": (
            "Plant hormones are chemical substances that regulate plant growth and development at very "
            "low concentrations. Auxins (IAA) promote cell elongation and are produced in shoot tips. "
            "Gibberellins promote stem elongation and seed germination. Cytokinins promote cell division "
            "and delay senescence. Abscisic acid (ABA) is a growth inhibitor associated with stress responses."
        ),
    },
    {
        "subject": "Biology", "class_num": 12,
        "chapter": "Genetics", "topic": "Mendel's Laws of Inheritance",
        "retrieved_context": (
            "Mendel's Law of Segregation states that the two alleles for each character segregate during "
            "gamete formation and each gamete receives only one allele. Mendel's Law of Independent "
            "Assortment states that alleles of different genes assort independently of each other during "
            "gamete formation. A monohybrid cross (Tt x Tt) gives a 3:1 phenotypic ratio."
        ),
    },
    {
        "subject": "Biology", "class_num": 12,
        "chapter": "Molecular Basis of Inheritance", "topic": "Transcription & Translation",
        "retrieved_context": (
            "Transcription is the process of copying genetic information from DNA to mRNA. RNA polymerase "
            "reads the template strand (3' to 5') and synthesizes mRNA (5' to 3'). Translation is the "
            "synthesis of protein from mRNA using ribosomes. The genetic code is triplet (codons), "
            "non-overlapping, degenerate, and universal. AUG is the start codon coding for methionine."
        ),
    },
    {
        "subject": "Biology", "class_num": 12,
        "chapter": "Evolution", "topic": "Darwin's Theory of Natural Selection",
        "retrieved_context": (
            "Darwin's Theory of Natural Selection proposes that variations exist within a population, "
            "organisms with favourable variations are more likely to survive and reproduce, these "
            "favourable variations are heritable, and over time, this leads to speciation. "
            "Evidence for evolution includes fossil records, comparative anatomy such as homologous "
            "and analogous structures, and biogeography."
        ),
    },
    {
        "subject": "Biology", "class_num": 12,
        "chapter": "Human Health and Disease", "topic": "Immune System & Vaccines",
        "retrieved_context": (
            "The immune system provides defence against pathogens. Innate immunity is non-specific and "
            "includes physical barriers such as skin and mucus, phagocytes, and natural killer cells. "
            "Adaptive immunity is specific and involves B lymphocytes (antibody-mediated) and T lymphocytes "
            "(cell-mediated). Vaccines introduce antigens to stimulate memory cell production without "
            "causing disease."
        ),
    },
    {
        "subject": "Biology", "class_num": 12,
        "chapter": "Biotechnology", "topic": "Recombinant DNA Technology",
        "retrieved_context": (
            "Recombinant DNA technology involves cutting DNA using restriction endonucleases at specific "
            "palindromic sequences, ligating the fragment into a vector such as a plasmid or bacteriophage "
            "using DNA ligase, transforming the recombinant vector into a host cell such as E. coli, "
            "and selecting transformed cells using antibiotic resistance markers. This technology enables "
            "production of proteins like insulin and vaccines."
        ),
    },

    # ─── Chemistry (10 topics) ──────────────────────────────────────────────
    {
        "subject": "Chemistry", "class_num": 11,
        "chapter": "Structure of Atom", "topic": "Bohr's Model & Atomic Spectra",
        "retrieved_context": (
            "Bohr's model postulates that electrons revolve around the nucleus in fixed circular orbits "
            "called stationary states without radiating energy. Energy is emitted or absorbed only when "
            "an electron transitions between orbits. The energy of each orbit is En = -13.6 divided by n^2 eV. "
            "The emission spectrum of hydrogen shows discrete lines corresponding to electron transitions."
        ),
    },
    {
        "subject": "Chemistry", "class_num": 11,
        "chapter": "Chemical Bonding", "topic": "Ionic and Covalent Bonds",
        "retrieved_context": (
            "Ionic bonds form by transfer of electrons from metal to non-metal, creating oppositely charged "
            "ions held by electrostatic attraction. Covalent bonds form by sharing of electrons between "
            "non-metals. The octet rule states atoms tend to achieve 8 electrons in their outermost shell. "
            "Electronegativity difference greater than 1.7 generally indicates ionic character."
        ),
    },
    {
        "subject": "Chemistry", "class_num": 11,
        "chapter": "Thermodynamics", "topic": "Laws of Thermodynamics & Gibbs Energy",
        "retrieved_context": (
            "The First Law of Thermodynamics states that energy cannot be created or destroyed: "
            "delta U = q + w. The Second Law states that entropy of an isolated system always increases. "
            "Gibbs Free Energy delta G = delta H - T times delta S determines spontaneity: "
            "delta G less than 0 means spontaneous, greater than 0 means non-spontaneous, equals 0 at equilibrium."
        ),
    },
    {
        "subject": "Chemistry", "class_num": 11,
        "chapter": "Equilibrium", "topic": "Le Chatelier's Principle & Equilibrium Constants",
        "retrieved_context": (
            "Le Chatelier's Principle states that if a system at equilibrium is disturbed, it shifts "
            "to partially counteract the disturbance. The equilibrium constant Kc equals concentration "
            "of products over reactants at constant temperature. Increasing concentration of reactants "
            "shifts equilibrium forward. Increasing pressure favours the side with fewer moles of gas."
        ),
    },
    {
        "subject": "Chemistry", "class_num": 11,
        "chapter": "Organic Chemistry", "topic": "Hydrocarbons - Alkanes Alkenes Alkynes",
        "retrieved_context": (
            "Alkanes with formula CnH(2n+2) are saturated hydrocarbons with only C-C single bonds and "
            "undergo substitution reactions with halogens in presence of UV light. Alkenes with formula "
            "CnH(2n) contain C=C double bond and undergo addition reactions. Alkynes with formula CnH(2n-2) "
            "contain C triple bond C. Markovnikov's rule states that in addition of HX to alkenes, "
            "H adds to the carbon with more hydrogen atoms."
        ),
    },
    {
        "subject": "Chemistry", "class_num": 12,
        "chapter": "Electrochemistry", "topic": "Electrolysis & Faraday's Laws",
        "retrieved_context": (
            "Faraday's First Law of Electrolysis states that the amount of substance deposited at an "
            "electrode is directly proportional to the quantity of charge passed. Faraday's Second Law "
            "states that when the same charge is passed, masses deposited are proportional to their "
            "equivalent weights. 1 Faraday equals 96500 C per mol, which is the charge of one mole of electrons."
        ),
    },
    {
        "subject": "Chemistry", "class_num": 12,
        "chapter": "Chemical Kinetics", "topic": "Rate Laws & Activation Energy",
        "retrieved_context": (
            "The rate of a chemical reaction is the change in concentration of reactant or product per "
            "unit time. The rate law expresses reaction rate as r = k times [A]^m times [B]^n. "
            "The Arrhenius equation relates rate constant to temperature: k = A times e^(-Ea over RT), "
            "where Ea is activation energy, R is the gas constant, and T is temperature in Kelvin."
        ),
    },
    {
        "subject": "Chemistry", "class_num": 12,
        "chapter": "Coordination Compounds", "topic": "Werner's Theory & Crystal Field Theory",
        "retrieved_context": (
            "Coordination compounds consist of a central metal atom or ion surrounded by ligands. "
            "Werner's theory distinguishes primary valency (oxidation state) from secondary valency "
            "(coordination number). Crystal Field Theory explains splitting of d-orbitals in octahedral "
            "field into t2g lower energy with 3 orbitals and eg higher energy with 2 orbitals, with "
            "crystal field splitting energy delta-o."
        ),
    },
    {
        "subject": "Chemistry", "class_num": 12,
        "chapter": "Aldehydes Ketones and Carboxylic Acids", "topic": "Nucleophilic Addition Reactions",
        "retrieved_context": (
            "Aldehydes and ketones undergo nucleophilic addition reactions at the carbonyl group C=O. "
            "Aldehydes are more reactive than ketones due to lesser steric hindrance and greater "
            "electrophilicity of the carbonyl carbon. Tollens' reagent (ammoniacal AgNO3) oxidises "
            "aldehydes to carboxylate and produces silver mirror. Fehling's solution is also used to "
            "distinguish aldehydes from ketones."
        ),
    },
    {
        "subject": "Chemistry", "class_num": 12,
        "chapter": "Polymers", "topic": "Addition vs Condensation Polymerisation",
        "retrieved_context": (
            "Addition polymerisation involves repeated addition of monomer molecules having double or "
            "triple bonds without elimination of any by-product. Examples include polyethylene from ethylene "
            "and PVC from vinyl chloride. Condensation polymerisation involves reaction between monomers "
            "with elimination of small molecules such as water or HCl. Examples include Nylon-6,6 from "
            "hexamethylenediamine and adipic acid, and polyester Dacron from ethylene glycol and "
            "terephthalic acid."
        ),
    },
]


async def main() -> None:
    os.makedirs("outputs/eval_run", exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"{'='*70}")
    print("  30-TOPIC PROMPT EVALUATION RUN")
    print(f"  Timestamp : {timestamp}")
    print(f"  Topics    : {len(TEST_INPUTS)} (10 Physics + 10 Biology + 10 Chemistry)")
    print(f"  Versions  : v1, v2, v3")
    print(f"{'='*70}\n")

    # Build pipeline
    prompt_manager = PromptManager(prompts_dir="prompts")
    llm_client     = MockLLMClient()
    generator      = ScriptGenerator(prompt_manager=prompt_manager, llm_client=llm_client)
    evaluator      = PromptEvaluator(script_generator=generator)
    comparator     = PromptVersionComparator(evaluator=evaluator)

    # Run comparison across all three versions
    report = await comparator.compare_versions(
        prompt_name="master",
        versions=["v1", "v2", "v3"],
        test_inputs=TEST_INPUTS,
    )

    # Print Summary
    print(report.summary_markdown)
    print(f"\n  Winning Version: {report.winning_version}\n")

    for v, res in report.results.items():
        print(f"  {v}  overall={res.overall_score:.4f}  "
              f"accuracy={res.metrics.accuracy:.4f}  "
              f"hal_rate={res.metrics.hallucination_rate:.4f}  "
              f"manual={res.metrics.manual_score:.4f}")

    # Export Files
    csv_path  = f"outputs/eval_run/benchmark_{timestamp}.csv"
    md_path   = f"outputs/eval_run/benchmark_{timestamp}.md"
    json_path = f"outputs/eval_run/benchmark_{timestamp}.json"

    comparator.export_to_csv(report, csv_path)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report.summary_markdown)

    # Build JSON summary
    summary = {
        "run_timestamp": timestamp,
        "total_topics": len(TEST_INPUTS),
        "versions_evaluated": report.versions_evaluated,
        "winning_version": report.winning_version,
        "results": {
            v: {
                "overall_score": res.overall_score,
                "sample_count": res.sample_count,
                "metrics": res.metrics.model_dump(),
            }
            for v, res in report.results.items()
        },
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\n  Outputs saved:")
    print(f"    CSV  -> {csv_path}")
    print(f"    MD   -> {md_path}")
    print(f"    JSON -> {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
