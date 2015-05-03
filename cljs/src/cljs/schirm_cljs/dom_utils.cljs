(ns schirm-cljs.dom-utils
  (:require [clojure.string :as string]))

(defn min-fill
  "Return a string s of at least min-len, prepending fill-char characters if necessary"
  [s min-len fill-char]
  (let [fill (- min-len (count s))]
    (if (< 0 fill)
      (str (apply str (repeat fill (or fill-char \ ))) s)
      s)))

(defn re-find-class
  "Match a regex against an elements classes and return the first match."
  [element re]
  (->> element .-classList array-seq (map #(second (re-matches re %))) (filter identity) first))

(defn element-at-pos
  "Use pos as the offset into the .textContents of children of parent.

  Return the element containing the pos as well as the local offset of pos."
  [parent pos]
  (let [children (-> parent .-children array-seq)]
    (loop [i 0
           lower 0]
      (let [ch (nth children i)
            upper (when ch (+ lower (-> ch .-textContent count)))]
        (cond (nil? ch) nil
              (<= upper pos) (recur (inc i) upper)
              :else [ch (- pos lower)])))))

(defn elements-between-pos
  "Like element-at-pos, but return all elements between start and end."
  [parent start end]
  (when (<= start end)
    (let [[start-element start-local] (element-at-pos parent start)]
      (if start-element
        (loop [e start-element
               e-end (+ (-> start-element .-textContent count) (- start start-local))
               res [start-element]]
          (if (< end e-end)
            {:elements res :local-start start-local :local-end (- (-> e .-textContent count) (- e-end end))}
            (if-let [n (.-nextElementSibling e)]
              (recur n (+ e-end (-> n .-textContent count)) (conj res n))
              {:elements res :local-start start-local :local-end (-> e .-textContent count)})))
        {}))))

(defn element-pos [element]
  (->> (iterate #(.-previousSibling %) element)
       (drop 1)
       (take-while identity)
       (map #(-> % .-textContent count))
       (reduce + 0)))

(defn lispify [s]
  (-> (string/replace s #"[A-Z]" "-$&") string/lower-case))

(defn camelcasify [s]
  (string/replace s #"-[A-z0-9]" #(string/upper-case (nth % 1))))

(defn create-element [type attrs]
  (let [e (.createElement js/document type)]
    (when-let [h (:inner-html attrs)] (set! (.-innerHTML e) h))
    (when-let [t (:inner-text attrs)] (set! (.-innerText e) t))
    (when-let [styles (:style attrs)]
      (doseq [[k v] styles]
        (aset (.-style e) (camelcasify (name k)) v)))
    (doseq [c (:class attrs)]
      (-> e .-classList (.add c)))
    (doseq [[k v] (filter #(not (contains? #{:inner-text :inner-html :style :class})) attrs)]
      (aset e (camelcasify (name k)) v))
    e))

(defn char-size
  "Compute the size of an 'X' in element.

  Size includes margin, border and padding. Return a map with :height,
  :width and :gap keys. :gap describes the size of the space between
  two lines of text."
  [element]
  (let [specimen (create-element "span" {:inner-html "X"})
        gap-specimen (create-element "span" {:inner-html "X<br>X"})]
    (.appendChild element specimen)
    (.appendChild element gap-specimen)
    (let [specimen-get-computed-style (fn [k] (-> js/window (.getComputedStyle specimen k) .-value (or 0)))
          specimen-frame-height (->> ["margin-top" "border-top" "border-bottom" "margin-bottom"]
                                     (map specimen-get-computed-style)
                                     (reduce +))
          specimen-height (+ specimen-frame-height (.-offsetHeight specimen))
          specimen-frame-width (->> ["margin-left" "border-left" "border-right" "margin-right"]
                                    (map specimen-get-computed-style)
                                    (reduce +))
          specimen-width (+ specimen-frame-width (.-offsetWidth specimen))
          ;; The size of the gap between two lines is required for an
          ;; accurate computation of the height of lines. It seems to
          ;; depend on the selected font.
          gap (- (+ (.-offsetHeight gap-specimen)
                    specimen-frame-height)
                 (* 2 specimen-height)) ;; ???
          ]
      (.removeChild element specimen)
      (.removeChild element gap-specimen)
      {:width specimen-width
       :height specimen-height
       :gap gap})))

(defn scrollbar-size
  ;; determine the height/width of a horizontal/vertical scrollbar
  []
  (let [div (create-element "div"
                            {:style {:width "100px"
                                     :height "100px"
                                     :overflow-x "scroll"
                                     :overflow-y "scroll"}})
        content (create-element "div"
                                {:style {:width "200px"
                                         :height "200px"}})]
    (.appendChild div content)
    (-> js/document .-body (.appendChild div))

    (let [h (- 100 (.-clientHeight div))
          v (- 100 (.-clientWidth div))]
      (-> js/document .-body (.removeChild div))
      {:vertical (if (< 0 v) v 0)
       :horizontal (if (< 0 h) h 0)})))

(defn select
  "Return the first DOM element matching selector.

  parent defaults to js/document when the first element of args is not
  a DOM element

  Example: (select parent 'div.container)
           (select parent 'div.container 'span)"
  [& args]
  (let [[element selector]
        (if (-> args first .-querySelector)
          [(first args) (rest args)]
          [js/document args])]
    (-> element (.querySelector (string/join \  (map name selector))))))

(defn document-ready
  "Execute f when the documents readyState changes to complete or is ready."
  [f]
  (if (= (.-readyState js/document) "complete")
    (f)
    (.addEventListener js/document "readystatechange"
                       (fn [] (when (= (.-readyState js/document) "complete")
                                (f))))))

(defn show
  "Show or hide the given DOM element."
  [element show]
  (set! (-> element .-style .-display)
        (if show "block" "none")))
