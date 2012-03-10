#! /usr/bin/env python

import time
import math
import qless
import redis
import unittest

class TestQless(unittest.TestCase):
    def setUp(self):
        self.redis  = redis.Redis()
        
        if len(self.redis.keys('*')):
            print 'This test must be run with an empty redis instance'
            exit(1)
        
        # Clear the script cache, and nuke everything
        self.redis.execute_command('script', 'flush')
        
        # The qless client we're using
        self.client = qless.client()
        # Our main queue
        self.q = self.client.queue('testing')
        
        # This represents worker 'a'
        self.a = self.client.queue('testing')
        self.a.worker = 'worker-a'
        # This represens worker b
        self.b = self.client.queue('testing')
        self.b.worker = 'worker-b'
        
        # This is just a second queue
        self.other = self.client.queue('other')
    
    def tearDown(self):
        self.redis.flushdb()
    
    def test_config(self):
        # Set this particular configuration value
        config = self.client.config
        config.set('testing', 'foo')
        self.assertEqual(config.get('testing'), 'foo')
        # Now let's get all the configuration options and make
        # sure that it's a dictionary, and that it has a key for 'testing'
        self.assertTrue(isinstance(config.get(), dict))
        self.assertEqual(config.get()['testing'], 'foo')
        # Now we'll delete this configuration option and make sure that
        # when we try to get it again, it doesn't exist
        config.set('testing')
        self.assertEqual(config.get('testing'), None)
    
    def test_put_get(self):
        # In this test, I want to make sure that I can put a job into
        # a queue, and then retrieve its data
        #   1) put in a job
        #   2) get job
        #   3) delete job
        jid = self.q.put({'test': 'put_get'})
        job = self.client.job(jid)
        self.assertEqual(job.priority, 0)
        self.assertEqual(job.data    , {'test': 'put_get'})
        self.assertEqual(job.tags    , [])
        self.assertEqual(job.worker  , '')
        self.assertEqual(job.state   , 'waiting')
        # Make sure the times for the history match up
        job.history[0]['put'] = math.floor(job.history[0]['put'])
        self.assertEqual(job.history , [{
            'q'    : 'testing',
            'put'  : math.floor(time.time())
        }])
    
    def test_push_peek_pop_many(self):
        # In this test, we're going to add several jobs, and make
        # sure that they:
        #   1) get put onto the queue
        #   2) we can peek at them
        #   3) we can pop them all off
        #   4) once we've popped them off, we can 
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        jids = [self.q.put({'test': 'push_pop_many', 'count': c}) for c in range(10)]
        self.assertEqual(len(self.q), len(jids), 'Inserting should increase the size of the queue')
        
        # Alright, they're in the queue. Let's take a peek
        self.assertEqual(len(self.q.peek(7)) , 7)
        self.assertEqual(len(self.q.peek(10)), 10)
        
        # Now let's pop them all off one by one
        self.assertEqual(len(self.q.pop(7)) , 7)
        self.assertEqual(len(self.q.pop(10)), 3)
    
    def test_data_access(self):
        # In this test, we'd like to make sure that all the data attributes
        # of the job can be accessed through __getitem__
        #   1) Insert a job
        #   2) Get a job,  check job['test']
        #   3) Peek a job, check job['test']
        #   4) Pop a job,  check job['test']
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        jid = self.q.put({'test': 'data_access'})
        job = self.client.job(jid)
        self.assertEqual(job['test'], 'data_access')
        job = self.q.peek()
        self.assertEqual(job['test'], 'data_access')
        job = self.q.pop()
        self.assertEqual(job['test'], 'data_access')
    
    def test_put_pop_priority(self):
        # In this test, we're going to add several jobs and make
        # sure that we get them in an order based on priority
        #   1) Insert 10 jobs into the queue with successively more priority
        #   2) Pop all the jobs, and ensure that with each pop we get the right one
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        jids = [self.q.put({'test': 'put_pop_priority', 'count': c}, priority=-c) for c in range(10)]
        last = len(jids)
        for i in range(len(jids)):
            job = self.q.pop()
            self.assertTrue(job['count'] < last, 'We should see jobs in reverse order')
            last = job['count']
    
    def test_put_failed(self):
        # In this test, we want to make sure that if we put a job
        # that has been failed, we want to make sure that it is
        # no longer reported as failed
        #   1) Put a job
        #   2) Fail that job
        #   3) Make sure we get failed stats
        #   4) Put that job on again
        #   5) Make sure that we no longer get failed stats
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        jid = self.q.put({'test': 'put_failed'})
        job = self.client.job(jid)
        self.q.fail(job, 'foo', 'some message')
        self.assertEqual(self.client.stats.failed(), {'foo':1})
        job.move('testing')
        self.assertEqual(len(self.q), 1)
        self.assertEqual(self.client.stats.failed(), {})
    
    def test_same_priority_order(self):
        # In this test, we'd like to make sure that jobs with identical
        # priority are popped off in the same order that that they were
        # given.
        #   1) Put a bunch of jobs
        #   2) Pop each of said jobs
        #   3) Make sure that we get them out in the order we put them
        pass
    
    def test_scheduled(self):
        # In this test, we'd like to make sure that we can't pop
        # off a job scheduled for in the future until it has been
        # considered valid
        #   1) Put a job scheduled for 10s from now
        #   2) Ensure an empty pop
        #   3) 'Wait' 10s
        #   4) Ensure pop contains that job
        # This is /ugly/, but we're going to path the time function so
        # that we can fake out how long these things are waiting
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        oldtime = time.time
        now = time.time()
        time.time = lambda: now
        jid = self.q.put({'test': 'scheduled'}, delay=10)
        self.assertEqual(self.q.pop(), None)
        self.assertEqual(len(self.q), 1)
        time.time = lambda: now + 11
        job = self.q.pop()
        self.assertNotEqual(job, None)
        self.assertEqual(job.id, jid)
        # Make sure that we reset it to the old system time function!
        time.time = oldtime
        self.assertTrue(sum(time.time() - time.time() for i in range(200)) < 0)
    
    def test_put_pop_complete_history(self):
        # In this test, we want to put a job, pop it, and then 
        # verify that its history has been updated accordingly.
        #   1) Put a job on the queue
        #   2) Get job, check history
        #   3) Pop job, check history
        #   4) Complete job, check history
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        jid = self.q.put({'test': 'put_history'})
        job = self.client.job(jid)
        self.assertEqual(math.floor(job.history[0]['put']), math.floor(time.time()))
        # Now pop it
        job = self.q.pop()
        job = self.client.job(jid)
        self.assertEqual(math.floor(job.history[0]['popped']), math.floor(time.time()))
    
    def test_move_queue(self):
        # In this test, we want to verify that if we put a job
        # in one queue, and then move it, that it is in fact
        # no longer in the first queue.
        #   1) Put a job in one queue
        #   2) Put the same job in another queue
        #   3) Make sure that it's no longer in the first queue
        self.assertEqual(len(self.q    ), 0, 'Start with an empty queue')
        self.assertEqual(len(self.other), 0, 'Start with an empty queue "other"')
        jid = self.q.put({'test': 'move_queues'})
        self.assertEqual(len(self.q), 1, 'Put failed')
        job = self.client.job(jid)
        job.move('other')
        self.assertEqual(len(self.q    ), 0, 'Move failed')
        self.assertEqual(len(self.other), 1, 'Move failed')
    
    def test_move_queue_popped(self):
        # In this test, we want to verify that if we put a job
        # in one queue, it's popped, and then we move it before
        # it's turned in, then subsequent attempts to renew the
        # lock or complete the work will fail
        #   1) Put job in one queue
        #   2) Pop that job
        #   3) Put job in another queue
        #   4) Verify that heartbeats fail
        self.assertEqual(len(self.q    ), 0, 'Start with an empty queue')
        self.assertEqual(len(self.other), 0, 'Start with an empty queue "other"')
        jid = self.q.put({'test': 'move_queue_popped'})
        self.assertEqual(len(self.q), 1, 'Put failed')
        job = self.q.pop()
        self.assertNotEqual(job, None)
        # Now move it
        job.move('other')
        self.assertEqual(self.q.heartbeat(job), False)
    
    def test_move_non_destructive(self):
        # In this test, we want to verify that if we move a job
        # from one queue to another, that it doesn't destroy any
        # of the other data that was associated with it. Like 
        # the priority, tags, etc.
        #   1) Put a job in a queue
        #   2) Get the data about that job before moving it
        #   3) Move it 
        #   4) Get the data about the job after
        #   5) Compare 2 and 4  
        self.assertEqual(len(self.q    ), 0, 'Start with an empty queue')
        self.assertEqual(len(self.other), 0, 'Start with an empty queue "other"')
        jid = self.q.put({'test': 'move_non_destructive'}, tags=['foo', 'bar'], priority=5)
        before = self.client.job(jid)
        before.move('other')
        after  = self.client.job(jid)
        self.assertEqual(before.tags    , ['foo', 'bar'])
        self.assertEqual(before.priority, 5)
        self.assertEqual(before.tags    , after.tags)
        self.assertEqual(before.data    , after.data)
        self.assertEqual(before.priority, after.priority)
        self.assertEqual(len(after.history), 2)
    
    def test_heartbeat(self):
        # In this test, we want to make sure that we can still 
        # keep our lock on an object if we renew it in time.
        # The gist of this test is:
        #   1) A gets an item, with positive heartbeat
        #   2) B tries to get an item, fails
        #   3) A renews its heartbeat successfully
        self.assertEqual(len(self.a), 0, 'Start with an empty queue')
        jid  = self.q.put({'test': 'heartbeat'})
        ajob = self.a.pop()
        self.assertNotEqual(ajob, None)
        bjob = self.b.pop()
        self.assertEqual(bjob, None)
        self.assertTrue(isinstance(self.a.heartbeat(ajob), float))
        self.assertTrue(self.a.heartbeat(ajob) >= time.time())
    
    def test_peek_pop_empty(self):
        # Make sure that we can safely pop from an empty queue
        #   1) Make sure the queue is empty
        #   2) When we pop from it, we don't get anything back
        #   3) When we peek, we don't get anything
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        self.assertEqual(self.q.pop(), None)
        self.assertEqual(self.q.peek(), None)
    
    def test_locks(self):
        # In this test, we're going to have two queues that point
        # to the same queue, but we're going to have them represent
        # different workers. The gist of it is this
        #   1) A gets an item, with negative heartbeat
        #   2) B gets the same item,
        #   3) A tries to renew lock on item, should fail
        #   4) B tries to renew lock on item, should succeed
        #   5) Both clean up
        jid = self.q.put({'test': 'locks'})
        # Reset our heartbeat for both A and B
        self.a._hb = -10
        self.b._hb = -10
        # Make sure a gets a job
        ajob = self.a.pop()
        self.assertNotEqual(ajob, None)
        # Now, make sure that b gets that same job
        bjob = self.b.pop()
        self.assertNotEqual(bjob, None)
        self.assertEqual(ajob.id, bjob.id)
        self.assertTrue(isinstance(self.b.heartbeat(bjob), float))
        self.assertTrue((self.b.heartbeat(bjob) + 11) >= time.time())
        self.assertEqual(self.a.heartbeat(ajob), False)
    
    def test_fail_failed(self):
        # In this test, we want to make sure that we can correctly 
        # fail a job
        #   1) Put a job
        #   2) Fail a job
        #   3) Ensure the queue is empty, and that there's something
        #       in the failed endpoint
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        self.assertEqual(len(self.client.stats.failed()), 0)
        jid = self.q.put({'test': 'fail_failed'})
        job = self.client.job(jid)
        self.q.fail(job, 'foo', 'Some sort of message')
        self.assertEqual(self.q.pop(), None)
        self.assertEqual(self.client.stats.failed(), {
            'foo': 1
        })
        results = self.client.stats.failed('foo')
        self.assertEqual(results['total'], 1)
        self.assertEqual(results['jobs'][0]['id'], jid)
    
    def test_pop_fail(self):
        # In this test, we want to make sure that we can pop a job,
        # fail it, and then we shouldn't be able to complete /or/ 
        # heartbeat the job
        #   1) Put a job
        #   2) Fail a job
        #   3) Heartbeat to job fails
        #   4) Complete job fails
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        self.assertEqual(len(self.client.stats.failed()), 0)
        jid = self.q.put({'test': 'pop_fail'})
        job = self.q.pop()
        self.assertNotEqual(job, None)
        self.q.fail(job, 'foo', 'Some sort of message')
        self.assertEqual(len(self.q), 0)
        self.assertEqual(self.q.heartbeat(job), False)
        self.assertEqual(self.q.complete(job) , False)
        self.assertEqual(self.client.stats.failed(), {
            'foo': 1
        })
        results = self.client.stats.failed('foo')
        self.assertEqual(results['total'], 1)
        self.assertEqual(results['jobs'][0]['id'], jid)
    
    def test_fail_complete(self):
        # Make sure that if we complete a job, we cannot fail it.
        #   1) Put a job
        #   2) Pop a job
        #   3) Complete said job
        #   4) Attempt to fail job fails
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        self.assertEqual(len(self.client.stats.failed()), 0)
        jid = self.q.put({'test': 'fail_complete'})
        job = self.q.pop()
        self.q.complete(job)
        self.assertEqual(self.q.fail(job, 'foo', 'Some sort of message'), False)
        self.assertEqual(len(self.client.stats.failed()), 0)
    
    def test_cancel(self):
        # In this test, we want to make sure that we can corretly
        # cancel a job
        #   1) Put a job
        #   2) Cancel a job
        #   3) Ensure that it's no longer in the queue
        #   4) Ensure that we can't get data for it
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        jid = self.q.put({'test': 'cancel'})
        job = self.client.job(jid)
        self.assertEqual(len(self.q), 1)
        job.cancel()
        self.assertEqual(len(self.q), 0)
        self.assertEqual(self.client.job(jid), None)
    
    def test_cancel_heartbeat(self):
        # In this test, we want to make sure that when we cancel
        # a job, that heartbeats fail, as do completion attempts
        #   1) Put a job
        #   2) Pop that job
        #   3) Cancel that job
        #   4) Ensure that it's no longer in the queue
        #   5) Heartbeats fail, Complete fails
        #   6) Ensure that we can't get data for it
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        jid = self.q.put({'test': 'cancel_heartbeat'})
        job = self.q.pop()
        job.cancel()
        self.assertEqual(len(self.q), 0)
        self.assertEqual(self.q.heartbeat(job), False)
        self.assertEqual(self.q.complete(job) , False)
        self.assertEqual(self.client.job(jid), None)
    
    def test_cancel_fail(self):
        # In this test, we want to make sure that if we fail a job
        # and then we cancel it, then we want to make sure that when
        # we ask for what jobs failed, we shouldn't see this one
        #   1) Put a job
        #   2) Fail that job
        #   3) Make sure we see failure stats
        #   4) Cancel that job
        #   5) Make sure that we don't see failure stats
        jid = self.q.put({'test': 'cancel_fail'})
        job = self.client.job(jid)
        self.q.fail(job, 'foo', 'some message')
        self.assertEqual(self.client.stats.failed(), {'foo': 1})
        job.cancel()
        self.assertEqual(self.client.stats.failed(), {})
    
    def test_cancel_heartbeat_complete(self):
        # In this test, we want to make sure that when we cancel a
        # job, that we can no longer heartbeat or complete a job
        #   1) Put a job
        #   2) Pop a job
        #   3) Cancel said job
        #   4) Attempts to complete it should fail
        #   5) Attempts to heartbeat it should fail
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        jid = self.q.put({'test': 'cancel_heartbeat_complete'})
        job = self.q.pop()
        job.cancel()
        self.assertEqual(len(self.q), 0)
        self.assertEqual(self.q.heartbeat(job), False)
        self.assertEqual(self.q.complete(job) , False)
        
    def test_complete(self):
        # In this test, we want to make sure that a job that has been
        # completed and not simultaneously enqueued are correctly 
        # marked as completed. It should have a complete history, and
        # have the correct state, no worker, and no queue
        #   1) Put an item in a queue
        #   2) Pop said item from the queue
        #   3) Complete that job
        #   4) Get the data on that job, check state
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        jid = self.q.put({'test': 'complete'})
        job = self.q.pop()
        self.assertNotEqual(job, None)
        self.assertEqual(self.q.complete(job), 'complete')
        job = self.client.job(jid)
        self.assertEqual(math.floor(job.history[-1]['done']), math.floor(time.time()))
        self.assertEqual(job.state , 'complete')
        self.assertEqual(job.worker, '')
        self.assertEqual(job.queue , '')
        self.assertEqual(len(self.q), 0)
    
    def test_complete_advance(self):
        # In this test, we want to make sure that a job that has been
        # completed and simultaneously enqueued has the correct markings.
        # It shouldn't have a worker, its history should be updated,
        # and the next-named queue should have that item.
        #   1) Put an item in a queue
        #   2) Pop said item from the queue
        #   3) Complete that job, re-enqueueing it
        #   4) Get the data on that job, check state
        #   5) Ensure that there is a work item in that queue
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        jid = self.q.put({'test': 'complete_advance'})
        job = self.q.pop()
        self.assertNotEqual(job, None)
        self.assertEqual(self.q.complete(job, next='testing'), 'waiting')
        job = self.client.job(jid)
        self.assertEqual(len(job.history), 2)
        self.assertEqual(math.floor(job.history[-2]['done']), math.floor(time.time()))
        self.assertEqual(math.floor(job.history[-1]['put' ]), math.floor(time.time()))
        self.assertEqual(job.state , 'waiting')
        self.assertEqual(job.worker, '')
        self.assertEqual(job.queue , 'testing')
        self.assertEqual(len(self.q), 1)
    
    def test_complete_fail(self):
        # In this test, we want to make sure that a job that has been
        # handed out to a second worker can both be completed by the
        # second worker, and not completed by the first.
        #   1) Hand a job out to one worker, expire
        #   2) Hand a job out to a second worker
        #   3) First worker tries to complete it, should fail
        #   4) Second worker tries to complete it, should succeed
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        jid = self.q.put({'test': 'complete_fail'})
        self.a._hb = -10
        ajob = self.a.pop()
        self.assertNotEqual(ajob, None)
        bjob = self.b.pop()
        self.assertNotEqual(bjob, None)
        self.assertEqual(self.a.complete(ajob), False)
        self.assertEqual(self.b.complete(bjob), 'complete')
        job = self.client.job(jid)
        self.assertEqual(math.floor(job.history[-1]['done']), math.floor(time.time()))
        self.assertEqual(job.state , 'complete')
        self.assertEqual(job.worker, '')
        self.assertEqual(job.queue , '')
        self.assertEqual(len(self.q), 0)
    
    def test_complete_state(self):
        # In this test, we want to make sure that if we try to complete
        # a job that's in anything but the 'running' state.
        #   1) Put an item in a queue
        #   2) DO NOT pop that item from the queue
        #   3) Attempt to complete the job, ensure it fails
        self.assertEqual(len(self.q), 0, 'Start with an empty queue')
        jid = self.q.put({'test': 'complete_fail'})
        job = self.client.job(jid)
        self.assertEqual(self.q.complete(job, next='testing'), False)
    
    def test_job_time_expiration(self):
        # In this test, we want to make sure that we honor our job
        # expiration, in the sense that when jobs are completed, we 
        # then delete all the jobs that should be expired according
        # to our deletion criteria
        #   1) First, set jobs-history to -1
        #   2) Then, insert a bunch of jobs
        #   3) Pop each of these jobs
        #   4) Complete each of these jobs
        #   5) Ensure that we have no data about jobs
        self.client.config.set('jobs-history', -1)
        jids = [self.q.put({'test': 'job_time_experiation', 'count':c}) for c in range(20)]
        for c in range(len(jids)):
            job = self.q.pop()
            self.q.complete(job)
        self.assertEqual(self.redis.zcard('ql:completed'), 0)
        self.assertEqual(len(self.redis.keys('ql:j:*')), 0)
    
    def test_job_count_expiration(self):
        # In this test, we want to make sure that we honor our job
        # expiration, in the sense that when jobs are completed, we 
        # then delete all the jobs that should be expired according
        # to our deletion criteria
        #   1) First, set jobs-history-count to 10
        #   2) Then, insert 20 jobs
        #   3) Pop each of these jobs
        #   4) Complete each of these jobs
        #   5) Ensure that we have data about 10 jobs
        self.client.config.set('jobs-history-count', 10)
        jids = [self.q.put({'test': 'job_count_expiration', 'count':c}) for c in range(20)]
        for c in range(len(jids)):
            job = self.q.pop()
            self.q.complete(job)
        self.assertEqual(self.redis.zcard('ql:completed'), 10)
        self.assertEqual(len(self.redis.keys('ql:j:*')), 10)
    
    def test_stats_waiting(self):
        # In this test, we're going to make sure that statistics are
        # correctly collected about how long items wait in a queue
        #   1) Ensure there are no wait stats currently
        #   2) Add a bunch of jobs to a queue
        #   3) Pop a bunch of jobs from that queue, faking out the times
        #   4) Ensure that there are now correct wait stats
        stats = self.client.stats.get('testing', time.time())
        self.assertEqual(stats['wait']['count'], 0)
        self.assertEqual(stats['run' ]['count'], 0)
        # This is /ugly/, but we're going to path the time function so
        # that we can fake out how long these things are waiting
        oldtime = time.time
        now = time.time()
        time.time = lambda: now
        jids = [self.q.put({'test': 'stats_waiting', 'count': c}) for c in range(20)]
        self.assertEqual(len(jids), 20)
        for i in range(len(jids)):
            time.time = lambda: (i + now)
            job = self.q.pop()
            self.assertNotEqual(job, None)
        # Make sure that we reset it to the old system time function!
        time.time = oldtime
        # Let's actually go ahead an add a test to make sure that the
        # system time has been reset. If the system time has not, it
        # could quite possibly impact the rest of the tests
        self.assertTrue(sum(time.time() - time.time() for i in range(200)) < 0)
        # Now, make sure that we see stats for the waiting
        stats = self.client.stats.get('testing', time.time())
        self.assertEqual(stats['wait']['count'], 20)
        self.assertEqual(stats['wait']['mean'] , 9.5)
        # This is our expected standard deviation
        self.assertTrue(stats['wait']['std'] - 5.916079783099 < 1e-8)
        # Now make sure that our histogram looks like what we think it
        # should
        self.assertEqual(stats['wait']['histogram'][0:20], [1] * 20)
        self.assertEqual(sum(stats['run' ]['histogram']), stats['run' ]['count'])
        self.assertEqual(sum(stats['wait']['histogram']), stats['wait']['count'])
    
    def test_stats_complete(self):
        # In this test, we want to make sure that statistics are
        # correctly collected about how long items take to actually 
        # get processed.
        #   1) Ensure there are no run stats currently
        #   2) Add a bunch of jobs to a queue
        #   3) Pop those jobs
        #   4) Complete those jobs, faking out the time
        #   5) Ensure that there are now correct run stats
        stats = self.client.stats.get('testing', time.time())
        self.assertEqual(stats['wait']['count'], 0)
        self.assertEqual(stats['run' ]['count'], 0)
        # This is /ugly/, but we're going to path the time function so
        # that we can fake out how long these things are waiting
        oldtime = time.time
        now = time.time()
        time.time = lambda: now
        jids = [self.q.put({'test': 'stats_waiting', 'count': c}) for c in range(20)]
        jobs = self.q.pop(20)
        self.assertEqual(len(jobs), 20)
        for i in range(len(jobs)):
            time.time = lambda: (i + now)
            job = jobs[i]
            self.q.complete(job)
        # Make sure that we reset it to the old system time function!
        time.time = oldtime
        # Let's actually go ahead an add a test to make sure that the
        # system time has been reset. If the system time has not, it
        # could quite possibly impact the rest of the tests
        self.assertTrue(sum(time.time() - time.time() for i in range(200)) < 0)
        # Now, make sure that we see stats for the waiting
        stats = self.client.stats.get('testing', time.time())
        self.assertEqual(stats['run']['count'], 20)
        self.assertEqual(stats['run']['mean'] , 9.5)
        # This is our expected standard deviation
        self.assertTrue(stats['run']['std'] - 5.916079783099 < 1e-8)
        # Now make sure that our histogram looks like what we think it
        # should
        self.assertEqual(stats['run']['histogram'][0:20], [1] * 20)
        self.assertEqual(sum(stats['run' ]['histogram']), stats['run' ]['count'])
        self.assertEqual(sum(stats['wait']['histogram']), stats['wait']['count'])
    
    def test_queues(self):
        # In this test, we want to make sure that the queues function
        # can correctly identify the numbers associated with that queue
        #   1) Make sure we get nothing for no queues
        #   2) Put delayed item, check
        #   3) Put item, check
        #   4) Put, pop item, check
        #   5) Put, pop, lost item, check
        self.assertEqual(len(self.q), 0)
        self.assertEqual(self.client.queues(), {})
        # Now, let's actually add an item to a queue, but scheduled
        self.q.put({'test': 'queues'}, delay=10)
        expected = {
            'name': 'testing',
            'stalled': 0,
            'waiting': 0,
            'running': 0,
            'scheduled': 1
        }
        self.assertEqual(self.client.queues(), [expected])
        self.q.put({'test': 'queues'})
        expected['waiting'] += 1
        self.assertEqual(self.client.queues(), [expected])
        self.q.put({'test': 'queues'})
        job = self.q.pop()
        expected['running'] += 1
        self.assertEqual(self.client.queues(), [expected])
        # Now we'll have to mess up our heartbeat to make this work
        self.q.put({'test': 'queues'})
        self.q._hb = -60
        job = self.q.pop()
        expected['stalled'] += 1
        self.assertEqual(self.client.queues(), [expected])
    
    def test_track(self):
        # In this test, we want to make sure that tracking works as expected.
        #   1) Check tracked jobs, expect none
        #   2) Put, Track a job, check
        #   3) Untrack job, check
        #   4) Track job, cancel, check
        self.assertEqual(self.client.tracked(), {'expired':{}, 'jobs':[]})
        job = self.client.job(self.q.put({'test':'track'}))
        job.track()
        self.assertEqual(len(self.client.tracked()['jobs']), 1)
        job.untrack()
        self.assertEqual(len(self.client.tracked()['jobs']), 0)
        job.track()
        job.cancel()
        self.assertEqual(len(self.client.tracked()['expired']), 1)
    
    def test_stats_failed(self):
        # In this test, we want to make sure that statistics are
        # correctly collected about how many items are currently failed
        pass
    
    def test_stats_failures(self):
        # In this test, we want to make sure that statistics are
        # correctly collected about how many items have failed
        pass
    
    # ==================================================================
    # In these tests, we want to ensure that if we don't provide enough
    # or correctly-formatted arguments to the lua scripts, that they'll
    # barf on us like we ask.
    # ==================================================================
    def test_lua_cancel(self):
        cancel = qless.lua('cancel', self.redis)
        # Providing in keys
        self.assertRaises(Exception, cancel, *(['foo'], ['deadbeef']))
        # Missing an id
        self.assertRaises(Exception, cancel, *([], []))
    
    def test_lua_complete(self):
        complete = qless.lua('complete', self.redis)
        # Not enough args
        self.assertRaises(Exception, complete, *([], []))
        # Providing a key, but shouldn't
        self.assertRaises(Exception, complete, *(['foo'], ['deadbeef', 'worker1', 'foo', 12345]))
        # Missing worker
        self.assertRaises(Exception, complete, *([], ['deadbeef']))
        # Missing queue
        self.assertRaises(Exception, complete, *([], ['deadbeef', 'worker1']))
        # Missing now
        self.assertRaises(Exception, complete, *([], ['deadbeef', 'worker1', 'foo']))
        # Malformed now
        self.assertRaises(Exception, complete, *([], ['deadbeef', 'worker1', 'foo', 'howdy']))
        # Malformed JSON
        self.assertRaises(Exception, complete, *([], ['deadbeef', 'worker1', 'foo', 12345, '[}']))
        # Not a number for delay
        self.assertRaises(Exception, complete, *([], ['deadbeef', 'worker1', 'foo', 12345, '{}', 'foo', 'howdy']))
    
    def test_lua_fail(self):
        fail = qless.lua('fail', self.redis)
        # Passing in keys
        self.assertRaises(Exception, fail, *(['foo'], ['deadbeef', 'worker1', 'foo', 'bar', 12345]))
        # Missing id
        self.assertRaises(Exception, fail, *([], []))
        # Missing worker
        self.assertRaises(Exception, fail, *([], ['deadbeef']))
        # Missing type
        self.assertRaises(Exception, fail, *([], ['deadbeef', 'worker1']))
        # Missing message
        self.assertRaises(Exception, fail, *([], ['deadbeef', 'worker1', 'foo']))
        # Missing now
        self.assertRaises(Exception, fail, *([], ['deadbeef', 'worker1', 'foo', 'bar']))
        # Malformed now
        self.assertRaises(Exception, fail, *([], ['deadbeef', 'worker1', 'foo', 'bar', 'howdy']))
        # Malformed data
        self.assertRaises(Exception, fail, *([], ['deadbeef', 'worker1', 'foo', 'bar', 12345, '[}']))
    
    def test_lua_failed(self):
        failed = qless.lua('failed', self.redis)
        # Passing in keys
        self.assertRaises(Exception, failed, *(['foo'], []))
        # Malformed start
        self.assertRaises(Exception, failed, *(['foo'], ['bar', 'howdy']))
        # Malformed limit
        self.assertRaises(Exception, failed, *(['foo'], ['bar', 0, 'howdy']))
    
    def test_lua_get(self):
        get = qless.lua('get', self.redis)
        # Passing in keys
        self.assertRaises(Exception, get, *(['foo'], ['deadbeef']))
        # Missing id
        self.assertRaises(Exception, get, *([], []))
    
    def test_lua_getconfig(self):
        getconfig = qless.lua('getconfig', self.redis)
        # Passing in keys
        self.assertRaises(Exception, getconfig, *(['foo']))
    
    def test_lua_heartbeat(self):
        heartbeat = qless.lua('heartbeat', self.redis)
        # Passing in keys
        self.assertRaises(Exception, heartbeat, *(['foo'], ['deadbeef', 'foo', 12345]))
        # Missing id
        self.assertRaises(Exception, heartbeat, *([], []))
        # Missing worker
        self.assertRaises(Exception, heartbeat, *([], ['deadbeef']))
        # Missing expiration
        self.assertRaises(Exception, heartbeat, *([], ['deadbeef', 'worker1']))
        # Malformed expiration
        self.assertRaises(Exception, heartbeat, *([], ['deadbeef', 'worker1', 'howdy']))
        # Malformed JSON
        self.assertRaises(Exception, heartbeat, *([], ['deadbeef', 'worker1', 12345, '[}']))
    
    def test_lua_peek(self):
        peek = qless.lua('peek', self.redis)
        # Passing in no keys
        self.assertRaises(Exception, peek, *([], [1, 12345]))
        # Passing in too many keys
        self.assertRaises(Exception, peek, *(['foo', 'bar'], [1, 12345]))
        # Missing count
        self.assertRaises(Exception, peek, *(['foo', []]))
        # Malformed count
        self.assertRaises(Exception, peek, *(['foo', ['howdy']]))
        # Missing now
        self.assertRaises(Exception, peek, *(['foo', [1]]))
        # Malformed now
        self.assertRaises(Exception, peek, *(['foo', [1, 'howdy']]))
    
    def test_lua_pop(self):
        pop = qless.lua('pop', self.redis)
        # Passing in no keys
        self.assertRaises(Exception, pop, *([], ['worker1', 1, 12345, 12346]))
        # Passing in too many keys
        self.assertRaises(Exception, pop, *(['foo', 'bar'], ['worker1', 1, 12345, 12346]))
        # Missing worker
        self.assertRaises(Exception, pop, *(['foo'], []))
        # Missing count
        self.assertRaises(Exception, pop, *(['foo'], ['worker1']))
        # Malformed count
        self.assertRaises(Exception, pop, *(['foo'], ['worker1', 'howdy']))
        # Missing now
        self.assertRaises(Exception, pop, *(['foo'], ['worker1', 1]))
        # Malformed now
        self.assertRaises(Exception, pop, *(['foo'], ['worker1', 1, 'howdy']))
        # Missing expires
        self.assertRaises(Exception, pop, *(['foo'], ['worker1', 1, 12345]))
        # Malformed expires
        self.assertRaises(Exception, pop, *(['foo'], ['worker1', 1, 12345, 'howdy']))
    
    def test_lua_put(self):
        put = qless.lua('put', self.redis)
        # Passing in no keys
        self.assertRaises(Exception, put, *([], ['deadbeef', '{}', 12345]))
        # Passing in two keys
        self.assertRaises(Exception, put, *(['foo', 'bar'], ['deadbeef', '{}', 12345]))
        # Missing id
        self.assertRaises(Exception, put, *(['foo'], []))
        # Missing data
        self.assertRaises(Exception, put, *(['foo'], ['deadbeef']))
        # Malformed data
        self.assertRaises(Exception, put, *(['foo'], ['deadbeef', '[}']))
        # Non-dictionary data
        self.assertRaises(Exception, put, *(['foo'], ['deadbeef', '[]']))
        # Non-dictionary data
        self.assertRaises(Exception, put, *(['foo'], ['deadbeef', '"foobar"']))
        # Missing now
        self.assertRaises(Exception, put, *(['foo'], ['deadbeef', '{}']))
        # Malformed now
        self.assertRaises(Exception, put, *(['foo'], ['deadbeef', '{}', 'howdy']))
        # Malformed priority
        self.assertRaises(Exception, put, *(['foo'], ['deadbeef', '{}', 12345, 'howdy']))
        # Malformed tags
        self.assertRaises(Exception, put, *(['foo'], ['deadbeef', '{}', 12345, 0, '[}']))
        # Malformed dleay
        self.assertRaises(Exception, put, *(['foo'], ['deadbeef', '{}', 12345, 0, '[]', 'howdy']))
    
    def test_lua_queues(self):
        queues = qless.lua('queues', self.redis)
        # Passing in keys
        self.assertRaises(Exception, queues, *(['foo'], [12345]))
        # Missing time
        self.assertRaises(Exception, queues, *([], []))
        # Malformed time
        self.assertRaises(Exception, queues, *([], ['howdy']))
    
    def test_lua_setconfig(self):
        setconfig = qless.lua('setconfig', self.redis)
        # Passing in keys
        self.assertRaises(Exception, setconfig, *(['foo'], []))
    
    def test_lua_stats(self):
        stats = qless.lua('stats', self.redis)
        # Passing in keys
        self.assertRaises(Exception, stats, *(['foo'], ['foo', 'bar']))
        # Missing queue
        self.assertRaises(Exception, stats, *([], []))
        # Missing date
        self.assertRaises(Exception, stats, *([], ['foo']))
    
    def test_lua_track(self):
        track = qless.lua('track', self.redis)
        # Passing in keys
        self.assertRaises(Exception, track, *(['foo'], []))
        # Unknown command
        self.assertRaises(Exception, track, *([], ['fslkdjf', 'deadbeef', 12345]))
        # Missing jid
        self.assertRaises(Exception, track, *([], ['track']))
        # Missing time
        self.assertRaises(Exception, track, *([], ['track', 'deadbeef']))
        # Malformed time
        self.assertRaises(Exception, track, *([], ['track', 'deadbeef', 'howdy']))

if __name__ == '__main__':
    unittest.main()