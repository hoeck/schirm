(ns schirm-cljs.keys
  (:require [clojure.string :as string]))

;; map browser key codes to Gtk key names used in schirm
;; see termkey.py
(def known-keys {33 "Page_Up",
                 34 "Page_Down",
                 35 "End",
                 36 "Home",
                 45 "Insert",
                 46 "Delete",

                 37 "Left",
                 38 "Up",
                 39 "Right",
                 40 "Down",

                 32 "Space",
                 8  "BackSpace",
                 9  "Tab",
                 13 "Enter",
                 27 "Esc",

                 112 "F1",
                 113 "F2",
                 114 "F3",
                 115 "F4",
                 116 "F5",
                 117 "F6",
                 118 "F7",
                 119 "F8",
                 120 "F9",
                 121 "F10",
                 122 "F11",
                 123 "F12"})

(defn get-key-chord [key]
  (->> [(when (:shift key) 'shift),
        (when (:control key) 'control),
        (when (:alt key ) 'alt),
        (string/lower-case (or (:name key) (.fromCharCode js/String (:code key))))]
       (filter identity)))

(defn handle-key-down [chords send key]
  (let [ascii-a 65
        ascii-z 90
        chord (get-key-chord key)
        handler (get chords chord)]
    (cond ;; key chords
          handler
          (handler send)
          ;; catch (control|alt)-* sequences
          (and (or (:control key) (:alt key))
               (<= ascii-a (:code key) ascii-z))
          (do (send (assoc key :name (.fromCharCode js/String (:code key))))
              true)
          ;; special keys
          (:name key)
          (do (send key)
              true)

          :else false
          )))

(defn setup-window-key-handlers [element chords send]
  (let [key-down-processed (atom false)
        chords (into {} (map (fn [[k,v]] [(map string/lower-case k) v]) chords))]
    (set! (.-onkeydown element)
          (fn [e]
            (let [key {:name (get known-keys (.-keyCode e))
                       :code (.-keyCode e)
                       :string "",
                       :shift (.-shiftKey e)
                       :alt (.-altKey e)
                       :control (.-controlKey e)}
                  processed (handle-key-down chords send key)]
              (reset! key-down-processed processed)
              (not processed))))
    (set! (.-onkeypress element)
          (fn [e]
            (let [key {:name nil
                       :string (.fromCharCode js/String (.-charCode e)),
                       :shift (.-shiftKey e)
                       :alt (.-altKey e)
                       :control (.-controlKey e)}]
              (if (and (:string key) (not @key-down-processed))
                (do (send key)
                    true)
                false))))
    (set! (.-onkeyup element)
          (fn [e] (reset! key-down-processed false)))))