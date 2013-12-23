(ns schirm-cljs.term
  (:require [cljs.core.async :as async
             :refer [<! >! chan close! sliding-buffer put! alts!]]

            [schirm-cljs.screen-tests :as tests]

            [schirm-cljs.screen :as screen]
            [schirm-cljs.keys :as keys]
            [schirm-cljs.dom-utils :as dom-utils])

  (:require-macros [cljs.core.async.macros :as m :refer [go alt!]]))

;; events -> chan
;; socket-messages -> chan

(defn invoke-screen-method [screen msg]
  (let [[meth & args] msg]
    ;;(.log js/console meth args)
    (case meth
      "set-line-origin" (apply screen/set-origin screen args)
      "reset"  (screen/reset screen)
      "resize" (screen/set-size screen (nth args 0))
      "insert-overwrite" (let [[line, col, string, attrs] args
                               style (apply screen/->CharacterStyle attrs)
                               ss (screen/StyledString. string style)]
                           (screen/update-line screen
                                               line
                                               #(screen/line-insert-overwrite % ss col)))
      "insert-line" (screen/insert-line screen (screen/create-line []) (nth args 0))
      "append-line" (screen/append-line screen (screen/create-line []))
      "adjust" (screen/adjust screen)
      "cursor" (let [[line, col] args]
                 (screen/set-cursor screen line col)))))

(def chords {;; browsers have space and shift-space bound to scroll page down/up
             ["space"] (fn [send] (send {:string " "}) true)
             ["shift" "space"] (fn [send] (send {:string " "}) true)
             ;; ignore F12 as this opens the browsers devtools
             ["F12"] (fn [send] false)})

(defn setup-keys [send-chan]
  (let [send-key (fn [key]
                   (let [message {:name :keypress :key key}]
                     (put! send-chan (.stringify js/JSON (clj->js message)))))]
    (keys/setup-window-key-handlers js/window chords send-key)))

(defn setup-screen [parent-element input-chan]
  (let [screen (screen/create-scrollback-screen parent-element)]
    (go
     (loop []
       (doseq [message (<! input-chan)]
               (invoke-screen-method screen message))
       (recur)))
    screen))

(defn setup-resize [container screen ws-send]
  (let [resize-screen #(let [new-size (screen/container-size container (.-element screen))
                             message (clj->js (assoc new-size :name :resize))]
                         (put! ws-send (.stringify js/JSON message)))]
    (set! (.-onresize js/window) resize-screen)
    (resize-screen)))

(defn setup-websocket [url in out]
  (let [ws (js/WebSocket. url)]
    (set! (.-onmessage ws)
          (fn [ev]
            (if (not= "" (.-data ev))
              (put! out (.parse js/JSON (.-data ev))))))
    (set! (.-onopen ws)
          #(go
            (loop []
              (let [msg (<! in)]
                (.send ws msg)
                (recur)))))))

(defn setup-terminal []
  (let [ws-send  (chan)
        ws-recv (chan)
        ws-url (format "ws://%s" (-> js/window .-location .-host))
        container (dom-utils/select 'body)
        screen (setup-screen container ws-recv)]
    (setup-keys ws-send)
    (setup-resize container screen ws-send)
    (setup-websocket ws-url ws-send ws-recv)))

(defn init []
  (dom-utils/document-ready setup-terminal))

(defn tests []
  (dom-utils/document-ready (fn []
                              (doseq [result (tests/run-tests)]
                                (.log js/console (str result))))))

(init)
