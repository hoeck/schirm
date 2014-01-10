(ns schirm-cljs.word-select
  (:require [schirm-cljs.dom-utils :as dom-utils]))

(defn select-in-line
  "Select a substring on a line."
  [line-element start-idx end-idx]
  (let [s (.getSelection js/document)
        r (.createRange js/document)
        [start-elem start-pos] (dom-utils/element-at-pos line-element start-idx)
        [end-elem   end-pos]   (dom-utils/element-at-pos line-element end-idx)]
    (if start-elem
      (.setStart r (-> start-elem .-childNodes (aget 0)) start-pos)
      (.setStartBefore r (.-firstChild line-element)))
    (if end-elem
      (.setEnd r (-> end-elem .-childNodes (aget 0))   end-pos)
      (.setEndAfter r (.-lastChild line-element)))
    (.removeAllRanges s)
    (.addRange s r)))

(defn word-boundaries
  "Detect boundaries of the word at idx in string.

  Use char-regex to define which characters make up a word.
  Returns nil or {:start number, :end number} when no word can be found."
  [string, idx, char-regex]
  (when (nth string idx nil)
    (let [char-regex (if (nil? char-regex)
                       #"[-,.\\/?%&#:_~A-Za-z0-9]"
                       char-regex)
          find-word-boundary (fn [indexes]
                               (->> indexes
                                    (map #(when (.test char-regex (nth string %)) %))
                                    (take-while #(not (nil? %)))
                                    last))]
      (when (.test char-regex (nth string idx))
        {:start (or (find-word-boundary (range idx -1 -1)) idx)
         :end   (if-let [i (find-word-boundary (range idx (count string)))]
                  (inc i)
                  idx)}))))

(defn select-word
  "Select the word on the line that has been double-clicked."
  [event screen]
  (when (or (-> event .-target .-tagName (= "SPAN"))
            (-> event .-target .-parentElement .-tagName (= "DIV")))
    (let [line (-> event .-target .-parentElement)
          rel-pos (/ (.-clientX event) (.-offsetWidth line))
          text (.-innerText line)
          idx (.round js/Math (* (.-width screen) rel-pos))
          boundaries (word-boundaries text idx)]
      (when (and boundaries (<= (:start boundaries) (:end boundaries)))
        (select-in-line line (:start boundaries) (:end boundaries)))))
  true)
