# Style notes for this writeup

Use these as editing checks, not as a claim that the paper conforms to ASD-STE100. That standard is for controlled technical documentation; this paper needs its research terms and citations.

1. **Put the result before its interpretation.** “Several factors suggest a weak gain.” → “Graph expansion found fewer targets. We then checked why.”
2. **Give each sentence one job.** “We mapped patches and ranked nodes, which showed a gap.” → “We mapped patches to nodes. We then ranked the nodes.”
3. **Keep the actor near the verb.** “The nodes, after several filtering steps, were ranked.” → “We filtered the nodes and ranked them.”
4. **Use active voice when the actor matters.** “The patches were mapped.” → “We mapped the patches.”
5. **Use a strong verb instead of a noun phrase.** “We performed an analysis of co-change.” → “We analysed co-change.”
6. **Choose a familiar word when it means the same thing.** “We utilised the graph.” → “We used the graph.”
7. **Define a term once, then reuse it.** “The target node, or gold node, was ranked.” → “We call an edited node a gold node. We rank gold nodes.”
8. **Use exact subjects instead of vague pointers.** “This suggests it helps.” → “The call graph helps find sibling edits.”
9. **State the comparison directly.** “There was an improvement of 11 points.” → “Graph expansion scored 36% versus 25%.”
10. **Keep uncertainty at the claim it qualifies.** “Possibly, perhaps, the method may help.” → “The method may help after tuning.”
11. **Put known information first and the new point last.** “A 23% recall was obtained by neighbours.” → “Call neighbours found 23% of the remaining nodes.”
12. **Cut framing that adds no fact.** “It is important to note that the run timed out.” → “The run timed out.”
13. **Avoid stock praise and grand claims.** “A robust and crucial advance.” → “A measured gain on this task set.”
14. **Vary sentence length without making fragments.** “We mapped nodes. We ranked nodes. We measured recall.” → “We mapped and ranked the nodes. Then we measured recall.”
15. **Use plain punctuation for asides.** “The graph—after filtering—held fewer nodes.” → “After filtering, the graph held fewer nodes.”
16. **Read each claim against its evidence.** “The graph improves agents.” → “Graph neighbours predict sibling edits in the model-free analysis.”

Sources: [ASD-STE100 Simplified Technical English, Issue 9](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf); [Federal Plain Language Guidelines](https://www.eac.gov/sites/default/files/eac_assets/1/6/FederalPLGuidelines.pdf); [Google developer documentation style guide: Voice and tone](https://developers.google.com/style/tone); [Microsoft Writing Style Guide: Use simple words, concise sentences](https://learn.microsoft.com/en-us/style-guide/word-choice/use-simple-words-concise-sentences); [Gopen and Swan, The Science of Scientific Writing](https://www.popecol.org/wp-content/uploads/2020/09/Gopen-Swan-1990.pdf); [Pinker, Why Academics Stink at Writing](https://stevenpinker.com/files/pinker/files/pinker_2014_why_academics_writing_stinks.pdf); [Human–LLM Coevolution: Evidence from Academic Writing](https://aclanthology.org/2025.findings-acl.657/).
