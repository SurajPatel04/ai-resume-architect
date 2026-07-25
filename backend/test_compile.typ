
#set document(title: "Test \<User\>")
#set page(margin: (x: 0.9in, y: 0.9in))
#set text(size: 11pt)

#show heading: it => [
  #set text(size: 11pt, weight: "regular")
  #block(smallcaps(it.body))
  #v(-0.2em)
  #line(length: 100%, stroke: 0.5pt)
  #v(0.1em)
]

#align(center)[
  #text(16pt, weight: "bold")[Test \<User\>]
  
  =Loc+ | 123 | a\@b
  
  C++ | \#git
]

= Summary
= Summary with C++ and - bullets and + and = at start

= Experience

*Comp \> \<* #h(1fr) 2020 - 2021 \
_Dev_, Remote
- = Revenue up 10%
- + Added C++
- - reduced bugs
