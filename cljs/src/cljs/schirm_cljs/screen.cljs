(ns schirm-cljs.screen
  (:require [clojure.string :as string]
            [schirm-cljs.dom-utils :as dom-utils]))

;; methods to modify the DOM screens
;; a screen consists of lines in a PRE element
;; each line is a SPAN, using nested SPANs to apply styles to parts of the lines

;; altering lines

(defn line-reverse
  "Takes a DOM screen line element and reverses all character attributes."
  [line]
  (doseq [s (-> line .-children array-seq)]
    (let [fg (dom-utils/re-find-class s #"f-(.*)")
          bg (dom-utils/re-find-class s #"b-(.*)")
          inv-color (fn [color-name]
                      (condp = color-name
                        nil "default-reversed"
                        "default-reversed" nil
                        color-name))
          js-class-list (.-classList s)]
      (when fg (.remove js-class-list (format "f-%s" fg)))
      (when bg (.remove js-class-list (format "b-%s" bg)))
      (when (inv-color fg) (.add js-class-list (format "b-%s" (inv-color fg))))
      (when (inv-color bg) (.add js-class-list (format "f-%s" (inv-color bg)))))))

;; same as the attribute part of pyte.screens.Char
(defrecord CharacterStyle [fg, bg, bold, italics, underscore, strikethrough, cursor])

(def character-style-defaults
  {:fg "default"
   :bg "default"
   :bold false
   :italics false
   :underscore false
   :strikethrough false
   :cursor false})

(defn get-classes [character-style]
  (let [cs character-style]
    (remove nil? [(when (:fg cs) (format "f-%s" (:fg cs)))
                  (when (:bg cs) (format "b-%s" (:bg cs)))
                  (when (:bold cs) "bold")
                  (when (:italics cs) "italics")
                  (when (:underscore cs) "underscore")
                  (when (:strikethrough cs) "strikethrough")
                  (when (:cursor cs) "cursor")])))

(defn get-class-string [character-style]
  (string/join \ (get-classes character-style)))

(def get-class-string-memoized (memoize get-class-string))

(defn get-style-from-classnames [classnames]
  (let [simple-classnames {"bold" :bold
                           "italics" :italics
                           "underscore" :underscore
                           "strikethrough" :strikethrough
                           "cursor" :cursor}]
    (->> classnames
         (map (fn [name]
                (or (when-let [key (get simple-classnames name)] [key true])
                    (when-let [color (second (re-matches #"f-(.*)" name))] [:fg color])
                    (when-let [color (second (re-matches #"b-(.*)" name))] [:bg color]))))
         (remove nil?)
         (into character-style-defaults)
         (map->CharacterStyle))))

(defn segment-style [segment]
  (-> segment .-classList array-seq get-style-from-classnames))

(defrecord StyledString [string style])

(defn default-styled-string [len]
  (StyledString. (apply str (repeat len \ )) (map->CharacterStyle character-style-defaults)))

(defn create-segment [styled-string]
  (let [elem (-> js/document (.createElement "span"))]
    (set! (.-className elem) (get-class-string-memoized (:style styled-string)))
    (set! (.-textContent elem) (:string styled-string))
    elem))

(defn styled-string-from-segment
  "Opposite of create-segment."
  [segment]
  (StyledString. (.-textContent segment) (segment-style segment)))

;; debugging lines

(defn readable-styled-string [styled-string]
  (apply vector
         (:string styled-string)
         (sort (map keyword (remove empty? (-> styled-string :style get-class-string (string/split \ )))))))

(defn into-styled-string [s & properties]
  (StyledString. s (get-style-from-classnames (map name properties))))

(defn line->readable [line]
  (->> line
       (map readable-styled-string)
       (into [])))

(defn readable->line
  [readable-line]
  (vec (map #(apply into-styled-string %) readable-line)))

;; line dom operations

(defn create-line
  "Create and return a line DOM element from a list of styled strings."
  [line]
  (let [line-element (.createElement js/document "div")]
    (doseq [s (if (empty? line)
                [(default-styled-string 1)]
                line)]
      (.appendChild line-element (create-segment s)))
    line-element))

(defn read-line
  "Create and return a line datastructure from the given DOM element."
  [line-element]
  (->> line-element .-children array-seq
       (map styled-string-from-segment)
       (into [])))

(defn line-insert
  "Insert the styled-string into line at pos."
  [line styled-string pos]
  (let [line-len (-> line .-textContent count)
        ;;ch (.-children line)
        [segment localpos] (if pos (dom-utils/element-at-pos line pos) [nil nil])]
    (if (nil? segment)
      ;; line empty / append beyond end -> fill with default style & append-at-end
      (do
        (when (< 0 (- pos line-len)) (.appendChild line (create-segment (default-styled-string (- pos line-len)))))
        (let [last-segment (.-lastElementChild line)]
          (if (and last-segment (-> last-segment segment-style (= (:style styled-string))))
            (set! (.-textContent last-segment) (str (.-textContent last-segment) (:string styled-string)))
            (.appendChild line (create-segment styled-string)))))
      ;; extend existing content, directly or using new segment when styles differ
      (cond
       ;; begin
       (= 0 localpos)
       (cond (= (:style styled-string) (segment-style segment)) ;; same style
             (set! (.-textContent segment) (str (:string styled-string) (.-textContent segment)))
             (and (.-previousElementSibling segment)
                  (= (:style styled-string) (segment-style (.-previousElementSibling segment)))) ;; prev sibling has same style
             (set! (-> segment .-previousElementSibling .-textContent)
                   (str (-> segment .-previousElementSibling .-textContent) (:string styled-string)))
             :else ;; different style
             (.insertBefore line (create-segment styled-string) segment))
       ;; middle
       :else
       (if (= (:style styled-string) (segment-style segment))
         ;; same style, just set textContent appropriately
         (let [before (subs (.-textContent segment) 0 localpos)
               after (subs (.-textContent segment) localpos)]
           (set! (.-textContent segment) (str before (:string styled-string) after)))
         ;; split this segment and insert new one
         (let [before (subs (.-textContent segment) 0 localpos)
               after (subs (.-textContent segment) localpos)]
           (set! (.-textContent segment) before)
           (.insertBefore line
                          (let [e (.createElement js/document "span")]
                            (set! (.-className e) (.-className segment))
                            (set! (.-textContent e) after)
                            e)
                          (.-nextElementSibling segment))
           (.insertBefore line (create-segment styled-string) (.-nextElementSibling segment))))))))

;; remove-line

(defn merge-similar-segments
  "Merge adjacent elements of similar styles into one.

  Do so for all elements including and between from and to."
  [from to]
  (let [merge-segments (fn [a b]
                         (set! (.-textContent a) (str (.-textContent a) (.-textContent b)))
                         (.removeChild (.-parentNode a) b))]
    (loop [a from
           b (and a (.-nextElementSibling a))]
      (cond (or (nil? a) (nil? b)) ;; done
            nil

            (or (= a b) (= to b)) ;; end
            (when (= (segment-style a) (segment-style b))
              (merge-segments a b)) ;; merge and stop

            (= (segment-style a) (segment-style b)) ;; merge and continue
            (let [next (.-nextElementSibling b)]
              (merge-segments a b)
              (recur a next))

            :else
            (recur b (.-nextElementSibling b))))))

(defn update-segment-text
  "Update the text in an element or remove it."
  [segment update-fn]
  (let [new-text (update-fn (.-textContent segment))]
    (if (= new-text "")
      (.removeChild (.-parentNode segment) segment)
      (set! (.-textContent segment) new-text))
    new-text))

(defn line-remove
  "Remove n chars starting at pos from line"
  [line pos n]
  (let [ch (.-children line)
        end (+ pos n)
        {segments :elements :keys [local-start local-end]} (dom-utils/elements-between-pos line pos end)]
    (cond (empty? segments) ;; nothing to remove
          nil

          (= (count segments) 1) ;; remove text inside a single segment
          (let [segment (first segments)
                prev (.-previousElementSibling segment)
                next (.-nextElementSibling segment)]
            (update-segment-text segment #(str (subs % 0 local-start) (subs % local-end)))
            (merge-similar-segments prev next))

          :else
          (do
            (doseq [s (-> segments next butlast)] (.removeChild line s))
            (let [first-segment (first segments)
                  first-segment-style (segment-style first-segment)
                  first-text (-> first-segment .-textContent (subs 0 local-start))
                  prev (or (.-previousElementSibling first-segment) first-segment)
                  last-segment (last segments)
                  last-segment-style (segment-style last-segment)
                  last-text (-> last-segment .-textContent (subs local-end))
                  next (or (.-nextElementSibling last-segment) last-segment)]
              (if (= first-segment-style last-segment-style) ;; meld all into first-segment
                (do (.removeChild line last-segment)
                    (update-segment-text first-segment (fn [_] (str first-text last-text))))
                (do
                  (update-segment-text first-segment (fn [_] first-text))
                  (update-segment-text last-segment (fn [_] last-text))))
              (merge-similar-segments prev next))))))

(defn line-insert-overwrite
  "Like line-insert but overwrite existing content."
  [line styled-string pos]
  (line-remove line pos (-> styled-string :string count))
  (line-insert line styled-string pos))

(defn line-set-cursor
  "Highlight char at pos using cursor styles."
  [line pos]
  (let [[segment localpos] (dom-utils/element-at-pos line pos)]
    (if segment
      (line-insert-overwrite line
                             (StyledString.
                              (-> segment .-textContent (nth localpos))
                              (assoc (segment-style segment) :cursor true))
                             pos)
      (line-insert-overwrite line
                             (StyledString. " " {:cursor true})
                             pos))))

(defn line-remove-cursor
  "Remove any cursor highlights from line."
  [line]
  (let [segment (dom-utils/select line '.cursor)
        pos (dom-utils/element-pos segment)]
    (line-insert-overwrite line
                           (StyledString.
                            (-> line .-textContent (nth pos))
                            (assoc (segment-style segment) :cursor false))
                           pos)))

(defn container-size
  "Compute the size in cols and lines of a pre element in container"
  [container pre]
  (let [blocksize (dom-utils/char-size pre)
        cols  (.floor js/Math (/ (.-clientWidth container)  (:width blocksize)))
        lines (.floor js/Math (/ (.-clientHeight container) (+ (:height blocksize) (:gap blocksize))))]
    {:lines lines, :cols cols}))

;; container

(defprotocol Screen
  "a terminal screen"
  (insert-line [this line pos])
  (append-line [this line])
  (remove-line [this pos])
  (update-line [this pos update-fn])
  (reset [this new-size])
  (set-origin [this screen0])
  (set-size [this screen0])
  (show [this show])
  (adjust [this]))

(def screen-markup
  "<div class=\"schirm-terminal\">
     <div class=\"terminal-screen\">
       <pre class=\"terminal-line-container\"></pre>
     </div>
     <pre class=\"terminal-alt-container\"></pre>
     <div class=\"terminal-alt-iframe-container\"></div>
   </div>")

(defn -append-missing-lines [screen pos]
  (let [existing-lines (- (-> screen .-element .-children .-length) (or (.-screen0 screen) 0))
        delta (- (+ 1 pos) existing-lines)]
    (when (< 0 delta)
      (dotimes [_ delta]
        (.appendChild (.-element screen) (create-line [(default-styled-string 1)]))))))

;; auto-scroll:
;;   automatically keep the bottom visible unless the user actively
;;   scrolls to the top

(def auto-scroll-activation-height 10)

(defn -auto-scroll
  "Scroll screen to the bottom if auto-scroll is active."
  [screen]
  (if (.-auto-scroll-active screen)
    (let [parent (-> screen .-element .-parentElement .-parentElement .-parentElement)]
      (set! (.-scrollTop parent)
            (- (.-scrollHeight parent)
               (.-clientHeight parent))))))

(defn -auto-scroll-check
  "Set the auto-scroll-active flag of screen"
  [screen]
  (let [parent (-> screen .-element .-parentElement .-parentElement)]
    (if (= (.-auto-scroll-last-height screen) (.-scrollHeight parent))
      ;; Whenever the user scrolls withing
      ;; autoScrollActivationAreaHeight pixels to the bottom,
      ;; automatically keep bottom content visible (==
      ;; scroll automatically)
      (set! (.-auto-scroll-active screen)
            (< (- (.-scrollHeight parent) auto-scroll-activation-height)
               (+ (.-scrollTop parent) (.-clientHeight parent))))
      ;; scroll event had been fired as result of adding lines
      ;; to the terminal and thus increasing its size, do not
      ;; deactivate autoscroll in that case
      (set! (.-auto-scroll-last-height screen)
            (.-scrollHeight parent)))))

(deftype ScrollbackScreen [;; the DOM element containing the terminal lines
                           element
                           ;; line origin
                           ^mutable screen0
                           ;; the current terminal size in lines
                           ^mutable size
                           ;; visibility
                           ^mutable visible
                           ;; auto scroll
                           ^mutable auto-scroll-active
                           ^mutable auto-scroll-last-height]
  ;; element is the PRE which contains the screens lines as children
  ;; its parent must be a div.terminal-screen
  IIndexed
  (-nth [this pos]
    (let [child (-> element .-children (aget (+ screen0 pos)))]
      (if (nil? child)
        (throw (js/Error. (format "no line at %s" pos)))
        child)))
  (-nth [this pos default]
    (let [child (-> element .-children (aget (+ screen0 pos)))]
      (if (nil? child)
        default
        child)))
  ICounted
  (-count [_] (-> element .-children .-length))
  Screen
  (insert-line [this line pos]
    (.insertBefore element line (nth this pos))
    this)
  (append-line [this line]
    (-append-missing-lines this (dec size))
    (.appendChild element line)
    this)
  (remove-line [this pos]
    (when-let [line (nth this pos nil)]
      (-> element (.removeChild line)))
    this)
  (update-line [this pos f]
    (if-let [line (nth this pos nil)]
      (f line)
      (do
        (-append-missing-lines this pos)
        (f (nth this pos))))
    this)
  (reset [this new-size]
    (set! (.-innerHTML element) "")
    (set! (.-size this) new-size)
    (set! (.-screen0 this) 0)
    this)
  (set-origin [this screen0]
    (set! (.-screen0 this) screen0)
    this)
  (set-size [this new-size]
    (set! (.-size this) new-size)
    this)
  (show [this show]
    (set! (.-visible this) show)
    (dom-utils/show (.-parentElement element) show))
  (adjust [this]
    ;; var adjustTrailingSpace = function() {
    ;;     if (linesElement.childNodes.length && ((linesElement.childNodes.length - screen0) <= self.size.lines)) {
    ;;         var historyHeight = linesElement.childNodes[screen0].offsetTop;
    ;;         // position the <pre> so that anything above the screen0 line is outside the termscreen client area
    ;;         linesElement.style.setProperty("top", -historyHeight);
    ;;         // set the termscreen div margin-top so that it covers all history lines (lines before line[screen0])
    ;;         linesElement.parentElement.style.setProperty("margin-top", historyHeight);
    ;;     }
    ;;     autoScroll();
    ;; };
    ;; this.adjustTrailingSpace = adjustTrailingSpace;
    (let [chlen (-> element .-children .-length)]
      (if (and chlen (< 0 (- chlen screen0) size))
        (let [scrollback-height (-> element .-children (aget screen0) .-offsetTop)]
          (-> element .-style (.setProperty "top" (- scrollback-height)))
          (-> element .-parentElement .-style (.setProperty "margin-top" scrollback-height))))
      (-auto-scroll this))
    this
    ))

(defn remove-cursor [screen]
  (let [segment (dom-utils/select (.-element screen) '.cursor)]
    (when segment
      (line-remove-cursor (.-parentElement segment)))))

(defn set-cursor [screen line-number pos]
  (remove-cursor screen)
  (update-line screen line-number #(line-set-cursor % pos)))

(deftype AltScreen [;; the DOM element containing the terminal lines
                    element
                    ;; the current terminal size in lines
                    ^mutable size
                    ;; visibility
                    ^mutable visible]
  ;; element is the PRE which contains the screens lines as children
  ;; its parent must be a div.terminal-screen
  IIndexed
  (-nth [this pos]
    (let [child (-> element .-children (aget pos))]
      (if (nil? child)
        (throw (js/Error. (format "no line at %s" pos)))
        child)))
  (-nth [this pos default]
    (let [child (-> element .-children (aget pos))]
      (if (nil? child)
        default
        child)))
  ICounted
  (-count [_] (-> element .-children .-length))
  Screen
  (insert-line [this line pos]
    (.insertBefore element line (nth this pos))
    this)
  (append-line [this line]
    (-append-missing-lines this (dec size))
    (condp = (.-nodeType line)
      (.-DOCUMENT_FRAGMENT_NODE js/document) ;; insert many lines
      (do
        ;; as there is no scrollback in this screen,
        ;; remove unneeded lines from the top
        (dotimes [i (min (-> element .-children .-length)
                           (-> line .-children .-length))]
          (.removeChild element (.-firstChild element)))
        ;; insert the DocumentFragment
        (.appendChild element line)
        ;; clean up superflous lines at the top
        (dotimes [i (max 0 (- (-> element .-children .-length) size))]
          (.removeChild element (.-firstChild element))))
      (.-ELEMENT_NODE js/document) ;; a single line
      (do (when-let [ch (nth this 0 nil)] (.removeChild element ch))
          (.appendChild element line))))
  (remove-line [this pos]
    (when-let [line (nth this pos nil)]
      (-> element (.removeChild line)))
    this)
  (update-line [this pos f]
    (if-let [line (nth this pos nil)]
      (f line)
      (do
        (-append-missing-lines this pos)
        (f (nth this pos))))
    this)
  (reset [this new-size]
    (set! (.-innerHTML element) "")
    (set! (.-size this) new-size)
    this)
  (set-origin [this screen0]
    this)
  (set-size [this new-size]
    (set! (.-size this) new-size)
    this)
  (show [this show]
    (set! (.-visible this) show)
    (dom-utils/show element show))
  (adjust [this]
    this))

(defn create-scrollback-screen [element]
  (let [screen (ScrollbackScreen. (-> element (.getElementsByClassName "terminal-line-container") (aget 0))
                                  0
                                  0
                                  true
                                  true
                                  0)]
    (set! (.-onscroll js/window) #(-auto-scroll-check screen))
    screen))

(defn create-alt-screen [element]
  (AltScreen. (-> element (.getElementsByClassName "terminal-alt-container") (aget 0))
              0
              true))

(defn create-screens
  "Create and return a ScrollbackScreen and an AltScreen."
  [parent-element]
  (let [parent-element (or parent-element (.-body js/document))]
    (set! (.-innerHTML parent-element) screen-markup)
    [(create-scrollback-screen parent-element)
     (create-alt-screen parent-element)]))

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;; (defn test []
;;   (let [line (-> js/window .-document (.querySelector "span.line"))]
;;     ;;(reverse-line line)
;;     ;;(line-insert line)
;;     ))
;;
;; (defn line [] (select "span.line"))
;;
;; (def st (StyledString.
;;          "==styled-text=="
;;          (map->CharacterStyle {:fg "red" :bold true})))
