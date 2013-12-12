(ns schirm-cljs.term
  (:require [cljs.core.async :as async
             :refer [<! >! chan close! sliding-buffer put! alts!]]

            [schirm-cljs.screen :as screen]
            [schirm-cljs.dom-utils :as dom-utils])

  (:require-macros [cljs.core.async.macros :as m :refer [go alt!]]))

;; (.write js/document "Hello, ClojureScript!")
;;
;; (defn test-fn [x]
;;   (print "x is" x))


;; events -> chan
;; socket-messages -> chan

(defn setup-screen [parent-element input-chan]
  (let [screen (screen/create-scrollback-screen parent-element)]
    (go
     (loop []
       (let [msg (<! input-chan)]
         ;; handle msg by invoking some screen method
         (.log js/console (format "setup-screen: %s" msg))
         (recur))))))

(defn setup-websocket [url in out]
  (let [ws (js/WebSocket. url)]
    (.log js/console "setup-websocket" ws)
    (set! (.-onmessage ws)
          (fn [ev]
            (.log js/console "recv" ev)
            (put! out (.-data ev))))
    (go
     (loop []
       (let [msg (<! in)]
         (.log js/console (format "send msg: %s" msg))
         (.send ws msg)
         (recur))))))

(defn setup-terminal
  []
  (let [screen-input-chan (chan)
        ;; setup websocket
        ;; setup resize chan
        ws-send  (chan)
        ws-recv (chan)
        ws-url (format "ws://%s" (-> js/window .-location .-host))]
    (setup-screen (dom-utils/select 'body) screen-input-chan)
    (setup-websocket ws-url ws-send ws-recv)
    (go (loop [] (.log js/console "-- recv via chan:" (<! ws-recv))))
    ))

(defn init []
  (.addEventListener js/document "readystatechange"
                     #(do
                        (when (== (.-readyState js/document) "complete")
                          (setup-terminal)))))

(init)
