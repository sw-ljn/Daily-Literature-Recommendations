# Literature Review Writing Template

## Purpose

Use this template after the iterative search and screening loop has stabilized and the final filtered references have been ranked.

The final review should be grounded in the included references only.

## Writing Rules

- Cite only papers that appear in the final filtered or included reference file.
- Distinguish direct evidence from your own synthesis.
- Prefer thematic synthesis over one-paper-at-a-time summaries.
- State uncertainty, disagreement, and missing evidence explicitly.
- Do not fabricate quotes, page numbers, venue facts, or empirical claims.
- Use the citation format selected during workflow setup. Supported options are `APA`, `MLA`, `Chicago Author-Date`, `Harvard`, `IEEE`, and `Vancouver`. If the user does not choose one of these supported formats, use `APA`.
- Follow the examples in `references/citation format/`.

## Suggested Files

Write the editable review draft to `review/literature_review.md`.

Then render the deliverable PDF at the workspace root:

```bash
python /path/to/write-literature-review/scripts/lit_review_pipeline.py render-review \
  --workspace review_workspace
```

## Suggested Structure

# Title

## Abstract
- Briefly state the topic, scope, and purpose of the review
- Summarize key themes or findings
- Highlight the main insight or contribution

---

## 1. Introduction
- Introduce the research area and its importance
- Provide necessary background context
- Identify key problems, debates, or gaps in the field
- State the purpose and scope of the review
- Outline the structure of the paper

---

## 2. Background and Key Concepts
- Define essential terms and concepts
- Provide theoretical or historical context if needed
- Clarify how terms are used in this review

---

## 3. Conceptual Framework / Organization of the Literature
- Explain how the literature is organized (e.g., by themes, methods, theories, time periods)
- Justify this structure
- Provide a roadmap for the main sections

---

## 4. Review of the Literature

### 4.1 Theme / Category A
- Describe the main idea or approach
- Summarize representative studies (grouped, not one-by-one)
- Highlight common methods, findings, or arguments
- Discuss strengths and limitations

### 4.2 Theme / Category B
- Same structure as above

### 4.3 Theme / Category C
- Same structure as above

*(Add more sections as needed)*

---

## 5. Synthesis and Comparative Analysis
- Compare different themes, approaches, or schools of thought
- Identify patterns, consistencies, and contradictions
- Discuss relationships between different strands of research
- Highlight overall trends in the literature

---

## 6. Critical Evaluation
- Assess the quality and robustness of existing research
- Identify methodological limitations or biases
- Evaluate the strength of evidence and arguments
- Discuss what is well-established vs. uncertain

---

## 7. Research Gaps
- Identify areas that are underexplored or unresolved
- Point out limitations in current knowledge
- Explain why these gaps matter

---

## 8. Future Directions
- Suggest promising directions for future research
- Propose improvements in methods, theory, or data
- Connect future work to identified gaps

---

## 9. Conclusion
- Summarize key insights from the review
- Reiterate the main contribution of the paper
- Emphasize the significance of the topic

---

## References
- List all cited works in a consistent academic format
```

## Drafting Instructions

When writing each section:

- lead with the synthesis, then support it with references
- keep claims proportional to evidence quality
- avoid overstating citation counts as quality
- use the ranked list to prioritize attention, not to silence less-cited but relevant work

## Final Checks

Before finalizing:

- verify every cited paper is in the final included list
- verify every major claim has supporting references
- verify the review scope matches the original user request
- verify the review does not rely on full-text claims for papers you did not actually inspect
