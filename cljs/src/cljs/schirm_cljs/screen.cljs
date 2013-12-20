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

(defn get-class-string [character-style]
  (let [cs character-style]
    (string/join \ (remove nil? [(when (:fg cs) (format "f-%s" (:fg cs)))
                                 (when (:bg cs) (format "b-%s" (:bg cs)))
                                 (when (:bold cs) "bold")
                                 (when (:italics cs) "italics")
                                 (when (:underscore cs) "underscore")
                                 (when (:strikethrough cs) "strikethrough")
                                 (when (:cursor cs) "cursor")]))))

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
         (into {})
         (map->CharacterStyle))))

(defn segment-style [segment]
  (-> segment .-classList array-seq get-style-from-classnames))

(defrecord StyledString [string style])

(defn default-styled-string [len]
  (StyledString. (apply str (repeat len \ )) (map->CharacterStyle {})))

(defn create-segment [styled-string]
  (let [elem (-> js/document (.createElement "span"))]
    (set! (.-className elem) (get-class-string (:style styled-string)))
    (set! (.-textContent elem) (:string styled-string))
    elem))

(defn styled-string-from-segment
  "Opposite of create-segment."
  [segment]
  (StyledString. (.-textContent segment) (segment-style segment)))

;; line dom operations

(defn create-line
  "Create and return a line DOM element."
  [line]
  (let [line-element (.createElement js/document "div")]
    (doseq [s line]
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
           (.insertBefore line (create-segment styled-string) (.-nextSegmentSibling segment))
           (.insertBefore line
                          (let [e (.createElement js/document "span")]
                            (set! (.-className e) (.-className segment))
                            (set! (.-textContent e) after)
                            e)
                          (.-nextSegmentSibling segment))))))))

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
    (line-insert-overwrite line
                           (StyledString.
                            (-> segment .-textContent (nth localpos))
                            (assoc (segment-style segment) :cursor true))
                           pos)))

(defn line-remove-cursor
  "Remove any cursor highlights from line."
  [line]
  (let [segment (dom-utils/select line '.cursor)
        pos (dom-utils/element-pos segment)]
    (line-insert-overwrite line
                           (StyledString.
                            (-> line .-textContent (nth pos))
                            (assoc (segment-style segment) :cursor nil))
                           pos)))

(defn container-size
  "Compute the size in cols and lines of a pre element."
  [e]
  (let [blocksize (dom-utils/char-size e)
        cols  (.floor js/Math (/ (.-clientWidth e)  (:width blocksize)))
        lines (.floor js/Math (/ (.-clientHeight e) (+ (:height blocksize) (:gap blocksize))))]
    {:lines lines, :cols cols}))

;; container

(defprotocol Screen
  "a terminal screen"
  (insert-line [this line pos])
  (remove-line [this pos])
  (update-line [this pos update-fn])
  (reset [this])
  (set-origin [this screen0])
  (set-size [this screen0])
  (adjust [this]))

(def scrollback-screen-markup
  "<div class=\"terminal-screen\">
      <pre class=\"terminal-line-container\"></pre>
   </div>")

(defn -append-missing-lines [screen pos]
  (let [existing-lines (- (-> screen .-element .-children .-length) (.-screen0 screen))
        delta (- (+ 1 pos) existing-lines)]
    (.log js/console "existing-lines" existing-lines "delta" delta)
    (when (< 0 delta)
      (dotimes [_ delta]
        (.appendChild (.-element screen) (create-line []))))))

(deftype ScrollbackScreen [;; the DOM element containing the terminal lines
                           element
                           ;; line origin
                           ^mutable screen0
                           ;; the current terminal  size in lines
                           size]
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
    (if (= pos size)
      (.appendChild element line)
      (.insertBefore element line (nth this pos)))
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
  (reset [this]
    (set! (.-innerHTML element) "")
    this)
  (set-origin [this screen0]
    (set! (.-screen0 this) screen0)
    this)
  (set-size [this new-size]
    (set! (.-size this) size)
    this)
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
      (if (and chlen (< (- chlen screen0) size))
        (let [scrollback-height (-> element .-children (aget screen0) .-offsetTop)]
          (-> element .-style (.setProperty "top" (- scrollback-height)))
          (-> element .-parentElement .-style (.setProperty "margin-top" scrollback-height)))))
    this
    ))

(defn create-scrollback-screen [parent-element]
  (let [parent-element (or parent-element (.-body js/document))]
    (set! (.-innerHTML parent-element) scrollback-screen-markup)
    (ScrollbackScreen. (-> parent-element (.getElementsByClassName "terminal-line-container") (aget 0))
                       0
                       0)))

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
